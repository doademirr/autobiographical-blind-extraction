import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from abx import capture, config, freeze, init, invoke, prepare, qualify, seal, store
from abx.errors import IntegrityError, IsolationError, UsageError

from .helpers import FIXTURE, FakeWorkspace, build


def new_workspace(fw: FakeWorkspace) -> store.Workspace:
    return init.init(fw.ws.root.parent / "w", [FIXTURE / "autobiography.txt"], [], False, config=fw.cfg)


def approve_fixture(ws: store.Workspace) -> None:
    for name in ("redactions.json", "eras.json"):
        store.write_json(ws.path(f"prepare/{name}"), store.read_json(FIXTURE / name))


class SealTest(unittest.TestCase):
    def test_malformed_or_empty_prediction_lines_are_refused_with_their_line(self):
        self.assertEqual(seal.predictions("# head\nP1: one\nP2:   two\n"), {"P1": "one", "P2": "two"})
        for text in ("P1: one\nP2 : two\n", "P1: one\nP2 - two\n", "P1:\nP2: two\n", "P1: a\nP1: b\n",
                     "P1: one\n- P2: two\n", "P1: one\n2. P2: two\n", "P1: one\nP\uff12: two\n"):
            with self.subTest(text=text), self.assertRaises(UsageError) as cm:
                seal.predictions(text)
            self.assertTrue("line" in str(cm.exception) or "P1" in str(cm.exception))


class InitTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()

    def tearDown(self):
        self.fw.close()

    def test_layout(self):
        ws = new_workspace(self.fw)
        self.assertFalse(ws.path("text/original.txt").stat().st_mode & stat.S_IWUSR)
        self.assertIn("Read(./sealed/**)", store.read_json(ws.path(".claude/settings.json"))["permissions"]["deny"])
        self.assertEqual(len(ws.path("sealed/ipip-120.csv").read_text().splitlines()), 121)
        self.assertTrue(ws.path("sealed/self-prediction.md").exists())
        config.load(ws)

    def test_refuses_git_repo_and_synced_folder(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".git").mkdir()
            with self.assertRaises(UsageError):
                init.init(Path(d) / "ws", [FIXTURE / "autobiography.txt"], [], False, config=self.fw.cfg)
            synced = Path(d) / "x" / "Dropbox" / "ws"
            synced.parent.mkdir(parents=True)
            (Path(d) / ".git").rmdir()
            with self.assertRaises(UsageError):
                init.init(synced, [FIXTURE / "autobiography.txt"], [], False, config=self.fw.cfg)
            init.init(synced, [FIXTURE / "autobiography.txt"], [], True, config=self.fw.cfg)

    def test_malformed_config_is_a_usage_error(self):
        ws = new_workspace(self.fw)
        cfg = store.read_json(ws.path("config.json"))
        cfg["lineages"]["codex"]["disable"] = "shell_tool"
        store.write_json(ws.path("config.json"), cfg)
        with self.assertRaises(UsageError):
            config.load(ws)

    def test_crosswalk_needs_one_coder_per_lineage(self):
        for coders in ([], ["claude"], ["claude", "claude"], ["claude", "codex", "codex"]):
            raw = {**self.fw.cfg, "roles": {**self.fw.cfg["roles"], "crosswalk_coders": coders}}
            with self.subTest(coders=coders), self.assertRaises(UsageError):
                config.parse(raw)

    def test_default_config_lists_are_independent_copies(self):
        with mock.patch("shutil.which", return_value=str(FIXTURE / "autobiography.txt")):
            a, b = init.default_config([]), init.default_config([])
        a["lineages"]["codex"]["disable"].append("x")
        a["lineages"]["codex"]["retained_tools"]["functions.exec"]["result"] = "changed"
        self.assertNotIn("x", b["lineages"]["codex"]["disable"])
        self.assertEqual(init.CODEX_RETAINED["functions.exec"]["result"], "code-mode host is disabled")


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()
        self.ws = new_workspace(self.fw)

    def tearDown(self):
        self.fw.close()

    def test_review_point_sends_nothing_until_approved(self):
        self.assertEqual(prepare.prepare(self.ws)["status"], "review")
        self.assertTrue(self.ws.path("prepare/segments-preview.txt").exists())
        self.assertEqual(self.fw.prompts_logged(), [])
        self.assertFalse(self.ws.path(invoke.QUALIFICATION).exists())

    def test_malformed_review_files_are_usage_errors(self):
        prepare.prepare(self.ws)
        eras = store.read_json(FIXTURE / "eras.json")
        for redactions, era_list in (({"approved": True, "names": {"Collins": None}}, eras),
                                     (store.read_json(FIXTURE / "redactions.json"), {**eras, "eras": [None]})):
            store.write_json(self.ws.path("prepare/redactions.json"), redactions)
            store.write_json(self.ws.path("prepare/eras.json"), era_list)
            with self.subTest(redactions=redactions), self.assertRaises(UsageError):
                prepare.prepare(self.ws)

    def test_an_era_named_like_a_prepare_file_does_not_collide(self):
        prepare.prepare(self.ws)
        eras = store.read_json(FIXTURE / "eras.json")
        eras["eras"][0]["id"] = "removed"
        store.write_json(self.ws.path("prepare/eras.json"), eras)
        store.write_json(self.ws.path("prepare/redactions.json"), store.read_json(FIXTURE / "redactions.json"))
        prepare.prepare(self.ws)
        self.assertIsInstance(store.read_json(self.ws.path("prepare/zoning/removed.json")), dict)
        self.assertIsInstance(store.read_json(self.ws.path("prepare/removed-sentences.json")), list)

    def test_review_files_edited_while_prepare_runs_are_caught(self):
        approve_fixture(self.ws)
        original_zone = prepare._zone

        def zone_then_edit(*args, **kwargs):
            out = original_zone(*args, **kwargs)
            store.write_json(self.ws.path("prepare/redactions.json"), {"approved": False, "names": {}})
            return out

        with mock.patch.object(prepare, "_zone", zone_then_edit), self.assertRaises(UsageError) as cm:
            prepare.prepare(self.ws)
        self.assertIn("changed while", str(cm.exception))
        names = store.read_json(FIXTURE / "redactions.json")["names"]
        for line in self.fw.prompts_logged():
            for name in names:
                self.assertNotIn(name, json.loads(line)["prompt"])

    def test_era_ids_differing_only_by_case_are_refused_before_any_call(self):
        prepare.prepare(self.ws)
        eras = store.read_json(FIXTURE / "eras.json")
        eras["eras"][1]["id"] = eras["eras"][0]["id"].upper()
        store.write_json(self.ws.path("prepare/eras.json"), eras)
        store.write_json(self.ws.path("prepare/redactions.json"), store.read_json(FIXTURE / "redactions.json"))
        with self.assertRaises(UsageError):
            prepare.prepare(self.ws)
        self.assertEqual(self.fw.prompts_logged(), [])

    def test_era_ids_are_checked(self):
        prepare.prepare(self.ws)
        eras = store.read_json(FIXTURE / "eras.json")
        eras["eras"][0]["id"] = "../e1"
        store.write_json(self.ws.path("prepare/eras.json"), eras)
        store.write_json(self.ws.path("prepare/redactions.json"), store.read_json(FIXTURE / "redactions.json"))
        with self.assertRaises(UsageError):
            prepare.prepare(self.ws)

    def test_zoning_builds_substrate_without_redacted_names(self):
        approve_fixture(self.ws)
        result = prepare.prepare(self.ws)
        self.assertEqual(result["status"], "done")
        self.assertEqual(set(result["stats"]), {"e1", "e2"})
        names = store.read_json(FIXTURE / "redactions.json")["names"]
        logged = [json.loads(line)["prompt"] for line in self.fw.prompts_logged()]
        self.assertTrue(any("abx-role: zoner" in p for p in logged))
        for p in logged:
            for name in names:
                self.assertNotIn(name, p)
        sentences = {s["id"]: s for s in store.read_json(self.ws.path("prepare/sentences.json"))}
        redacted = self.ws.path("prepare/redacted.txt").read_text()
        labels = store.read_json(self.ws.path("prepare/zoning/e1.json"))
        substrate = self.ws.path("prepare/substrate/e1.md").read_text()
        kept_lines = [line for line in substrate.splitlines() if line.startswith("[s")]
        self.assertEqual(len(kept_lines), sum(1 for lab in labels.values() if lab == "keep"))
        for line in kept_lines:
            s = sentences[line[1:7]]
            self.assertEqual(line[9:], redacted[s["start"]:s["end"]])
        self.assertIn("[…]", substrate)
        q = store.read_json(self.ws.path(invoke.QUALIFICATION))
        self.assertEqual(q["codex"]["evidence"]["registry"], sorted(init.CODEX_RETAINED))
        self.assertEqual(q["claude"]["resolved_model"], "fake-claude-1")
        self.assertEqual(q["claude"]["evidence"]["leak_probe"]["verdict"], "clean")
        evidence = sorted(p.name for p in self.ws.root.glob("run/qualification-evidence/*.json"))
        self.assertIn("codex-retained-functions.exec.json", evidence)
        self.assertIn("claude-control-mcp.json", evidence)


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()
        self.ws = build(self.fw, until="freeze")

    def tearDown(self):
        self.fw.close()

    def test_stages_before_a_are_closed_after_freeze(self):
        before = len(self.fw.prompts_logged())
        for stage in (prepare.prepare, seal.seal, freeze.freeze):
            with self.subTest(stage=stage.__module__), self.assertRaises(UsageError):
                stage(self.ws)
        self.assertEqual(len(self.fw.prompts_logged()), before)

    def test_tampered_frozen_file_stops_every_stage_before_any_write(self):
        path = self.ws.path("prepare/substrate/e1.md")
        path.write_text(path.read_text() + "\n[s99999] planted\n")
        for stage in (prepare.prepare, seal.seal, freeze.freeze):
            with self.subTest(stage=stage.__module__), self.assertRaises(IntegrityError):
                stage(self.ws)

    def test_freeze_refuses_preparation_edited_after_prepare(self):
        fw = FakeWorkspace()
        try:
            ws = build(fw, until="prepare")
            eras = store.read_json(ws.path("prepare/eras.json"))
            eras["eras"][1]["segment_ids"].insert(0, eras["eras"][0]["segment_ids"].pop())
            store.write_json(ws.path("prepare/eras.json"), eras)
            for name in ("self-prediction.md", "ipip-120.csv"):
                ws.path(f"sealed/{name}").write_text((FIXTURE / name).read_text())
            seal.seal(ws)
            with self.assertRaises(UsageError) as cm:
                freeze.freeze(ws)
            self.assertIn("eras.json", str(cm.exception))
        finally:
            fw.close()

    def test_cli_reports_a_removed_frozen_config_as_integrity(self):
        import contextlib
        import io
        import sys

        sys.path.insert(0, str(FIXTURE.parent.parent / "scripts"))
        import run as cli

        self.ws.path("config.json").unlink()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["extract", str(self.ws.root)]), 4)

    def test_cli_checks_integrity_before_estimating(self):
        import contextlib
        import io
        import sys

        sys.path.insert(0, str(FIXTURE.parent.parent / "scripts"))
        import run as cli

        cfg = store.read_json(self.ws.path("config.json"))
        cfg["runs"] = 1
        store.write_json(self.ws.path("config.json"), cfg)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["extract", str(self.ws.root)]), 4)

    def test_capture_cli_that_cannot_start_is_recorded_and_fails_closed(self):
        from abx.errors import CallFailed

        with mock.patch("abx.invoke.execute", side_effect=CallFailed("cannot start")), \
                self.assertRaises(IsolationError):
            qualify.qualify(self.ws, self.fw.config)
        record = store.read_json(self.ws.path("run/qualification-evidence/claude-baseline.json"))
        self.assertFalse(record["passed"])

    def test_frozen_instrument_copy_is_protected(self):
        from abx import extract

        path = self.ws.path("prereg/instrument/ipip-neo-120.json")
        path.write_text(path.read_text().replace('"key": -1', '"key": 1', 1))
        with self.assertRaises(IntegrityError):
            extract.extract(self.ws)


class QualifyFailureTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()
        self.ws = new_workspace(self.fw)
        prepare._stage_method(self.ws)

    def tearDown(self):
        self.fw.close()

    def _qualify(self, env, cfg=None):
        with mock.patch.dict(os.environ, env):
            return qualify.qualify(self.ws, cfg or self.fw.config)

    def test_forbidden_tool_in_registry_fails(self):
        with self.assertRaises(IsolationError) as cm:
            self._qualify({"ABX_FAKE_CAPTURE_EXTRA_TOOL": "exec_command"})
        self.assertIn("not retained", str(cm.exception))
        self.assertNotIn("exec_command", str(cm.exception))

    def test_retained_codex_tool_with_unpinned_result_fails(self):
        for result in ("ok", '{"accepted":true}'):
            with self.subTest(result=result), self.assertRaises(IsolationError) as cm:
                self._qualify({"ABX_FAKE_CODEX_CAPTURE_RESULT": result})
            self.assertIn("codex", str(cm.exception))
            self.assertIn("functions.", str(cm.exception))

    def test_claude_scripted_read_with_unpinned_result_fails(self):
        with self.assertRaises(IsolationError) as cm:
            self._qualify({"ABX_FAKE_CLAUDE_CAPTURE_RESULT": "file contents"})
        self.assertIn("claude", str(cm.exception))

    def test_leak_is_exit_3_and_cli_error_or_timeout_is_exit_2(self):
        for leak in ("They are an ABXPROFILECANARY type.", "Some facts about them."):
            with self.subTest(leak=leak), self.assertRaises(IsolationError) as cm:
                self._qualify({"ABX_FAKE_LEAK": leak})
            self.assertEqual(cm.exception.exit_code, 3)
        with self.assertRaises(IsolationError):
            self._qualify({"ABX_FAKE_RAW": '{"answer": "NONE", "profile": "ABXPROFILECANARY"}'})
        for env in ({"ABX_FAKE_FAIL": "1"}, {"ABX_FAKE_RAW": '{"answer": "NONE", "extra": 1}'}):
            with self.subTest(env=env), self.assertRaises(UsageError) as cm:
                self._qualify(env)
            self.assertEqual(cm.exception.exit_code, 2)
        slow = config.Config(**{**self.fw.config.__dict__, "timeout_s": 2})
        with self.assertRaises(UsageError):
            self._qualify({"ABX_FAKE_SLEEP": "5"}, slow)

    def _locked(self, traffic=(), forward=True, code=0, status="success", requests=None, scripted=None,
                baseline=None):
        T = capture.Traffic
        requests = requests or ({"model": "fake-codex-1", "input": []},)
        lin = self.fw.config.lineage("codex")
        cfg = config.Config(**{**self.fw.config.__dict__, "lineages": {
            **self.fw.config.lineages, "codex": config.Lineage(**{**lin.__dict__, "capture_forward": forward})}})
        terminal = [invoke.Event("turn.completed" if status == "success" else "turn.failed")]
        run = qualify.Run(capture.Evidence.of(requests, [T(*t) for t in traffic]), code,
                          invoke.Result(status=status, events=terminal))
        with qualify.Canary() as canary:
            return qualify._locked_problems("codex", cfg, run, canary, scripted, baseline=baseline)

    OK_TRAFFIC = (("GET", "/codex-up/models", "forwarded", 200), ("GET", "/codex-up/responses", "ws-refused"),
                  ("POST", "/backend-api/codex/analytics-events/events", "refused"))

    def test_forwarded_transport_disables_compression_even_for_unlocked_controls(self):
        lin = self.fw.config.lineage("codex")
        cfg = config.Config(**{**self.fw.config.__dict__, "lineages": {
            **self.fw.config.lineages, "codex": config.Lineage(**{**lin.__dict__, "capture_forward": True})}})
        with capture.Capture("codex") as cap:
            args, _ = qualify._codex_transport(cfg, cap)
        self.assertIn("enable_request_compression", args[args.index("--disable") + 1:][:1])

    def test_claude_capture_rejects_traffic_other_than_whole_inference(self):
        T = capture.Traffic
        events = [invoke.Event("system", "init"), invoke.Event("result", "success")]
        for extra in (T("POST", "/v1/messages", "unreadable"), T("POST", "/v1/messages", "incomplete"),
                      T("GET", "/v1/models", "refused")):
            with self.subTest(extra=extra), qualify.Canary() as canary:
                run = qualify.Run(capture.Evidence.of(({"model": "m", "messages": []},),
                                                      [extra, T("POST", "/v1/messages", "captured")]),
                                  0, invoke.Result(status="success", events=events))
                self.assertTrue(qualify._locked_problems("claude", self.fw.config, run, canary, None))

    def test_every_locked_capture_checks_transport_and_cli_success(self):
        ok = self.OK_TRAFFIC
        self.assertEqual(self._locked(ok), [])
        for bad in ((*ok, ("POST", "/backend-api/ps/mcp", "refused")),
                    (("GET", "/codex-up/models", "forwarded", 500),),
                    (("GET", "/codex-up/models", "forwarded", 304),),
                    (("GET", "/backend-api/wham/x", "ws-refused"),),
                    (("POST", "/backend-api/other", "refused"),),
                    (*ok, ("POST", "/codex-up/count_tokens", "counted")),
                    (*ok, ("POST", "/codex-up/other", "captured")),
                    (*ok, ("GET", "/codex-up/models", "mystery")),
                    (*ok, ("POST", "/codex-up/models", "forwarded", 200))):
            with self.subTest(bad=bad):
                self.assertTrue(self._locked(bad))
        self.assertTrue(self._locked(ok, code=1))
        self.assertTrue(self._locked(ok, status="failed"))

    def test_every_request_registry_is_checked(self):
        def req(*tools):
            names = [{"type": "function", "name": t} for t in tools]
            return {"model": "fake-codex-1", "input": [{"type": "additional_tools", "tools": [
                {"type": "namespace", "name": "functions", "tools": names}]}]}

        clean = req("exec", "wait")
        self.assertEqual(self._locked(self.OK_TRAFFIC, requests=(clean, clean)), [])
        problems = self._locked(self.OK_TRAFFIC, requests=(clean, req("exec", "wait", "exec_command")))
        self.assertTrue(any("not retained" in p for p in problems))
        later = self._locked(self.OK_TRAFFIC, requests=(clean,), baseline=("functions.exec",))
        self.assertTrue(any("baseline" in p for p in later))

    def test_scripted_result_must_match_exactly_in_type(self):
        wrapped = [{"type": "file", "text": "code-mode host is disabled"}]
        sent = [{"model": "fake-codex-1", "input": []},
                {"model": "fake-codex-1",
                 "input": [{"type": "function_call_output", "call_id": "c1", "output": wrapped}]}]
        problems = self._locked(self.OK_TRAFFIC, requests=sent, scripted=("c1", "code-mode host is disabled"))
        self.assertTrue(any("pinned" in p for p in problems))

    def test_canary_in_an_earlier_message_or_thinking_is_a_leak(self):
        for env in ({"ABX_FAKE_PRELUDE": "I recall ABXPROFILECANARY."},
                    {"ABX_FAKE_THINKING": "The profile says ABXPROFILECANARY."}):
            with self.subTest(env=env), self.assertRaises(IsolationError):
                self._qualify(env)

    def test_canary_on_stderr_is_a_leak(self):
        with self.assertRaises(IsolationError):
            self._qualify({"ABX_FAKE_STDERR": "loaded profile ABXPROFILECANARY"})

    def test_missing_codex_login_is_recorded_then_exit_2(self):
        lin = self.fw.config.lineage("codex")
        cfg = config.Config(**{**self.fw.config.__dict__, "lineages": {
            **self.fw.config.lineages,
            "codex": config.Lineage(**{**lin.__dict__, "auth_file": "/nonexistent/auth.json"})}})
        with self.assertRaises(UsageError) as cm:
            qualify.qualify(self.ws, cfg)
        self.assertEqual(cm.exception.exit_code, 2)
        self.assertFalse(store.read_json(self.ws.path("run/qualification-evidence/codex-setup.json"))["passed"])

    def test_canary_in_a_codex_error_notice_is_a_leak(self):
        with self.assertRaises(IsolationError):
            self._qualify({"ABX_FAKE_ERROR_NOTICE": "reconnecting for ABXPROFILECANARY"})

    def test_failure_before_any_stream_is_exit_2_not_a_leak(self):
        with self.assertRaises(UsageError):
            self._qualify({"ABX_FAKE_NO_INIT": "1", "ABX_FAKE_FAIL": "1"})

    def test_leak_control_needs_success_and_its_own_planted_canary(self):
        with mock.patch.dict(os.environ, {"ABX_FAKE_READ_INSTRUCTIONS": "1"}):
            for lineage in ("claude", "codex"):
                self.assertEqual(qualify.leak_control(self.ws, self.fw.config, lineage)["verdict"], "leak")
        with mock.patch.dict(os.environ, {"ABX_FAKE_READ_INSTRUCTIONS": "1", "ABX_FAKE_FAIL": "1"}), \
                self.assertRaises(IsolationError):
            qualify.leak_control(self.ws, self.fw.config, "claude")
        with mock.patch.dict(os.environ, {"ABX_FAKE_LEAK": "ABXPROFILECANARY"}), self.assertRaises(IsolationError):
            qualify.leak_control(self.ws, self.fw.config, "claude")

    def test_probe_without_init_or_final_message_never_passes(self):
        with self.assertRaises(IsolationError):
            self._qualify({"ABX_FAKE_NO_INIT": "1"})
        with self.assertRaises(UsageError):
            self._qualify({"ABX_FAKE_NO_MESSAGE": "1"})
        record = store.read_json(self.ws.path("run/probes/leak-codex.json"))
        self.assertEqual(record["verdict"], "error")
        self.assertNotIn("answer", json.dumps(record))

if __name__ == "__main__":
    unittest.main()
