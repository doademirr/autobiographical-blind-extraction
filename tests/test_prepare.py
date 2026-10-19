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
        self.assertEqual(q["codex"]["evidence"]["registry"], list(init.CODEX_RETAINED))
        self.assertEqual(q["claude"]["resolved_model"], "fake-claude-1")
        self.assertEqual(q["claude"]["evidence"]["leak_probe"]["status"], "success")


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
        self.assertIn("functions.exec_command", str(cm.exception))

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

    def _locked(self, traffic, forward=True, code=0, status="success"):
        cap = capture.Capture("codex")
        cap.requests.append({"model": "fake-codex-1", "input": []})
        cap.traffic.extend(traffic)
        lin = self.fw.config.lineage("codex")
        cfg = config.Config(**{**self.fw.config.__dict__, "lineages": {
            **self.fw.config.lineages, "codex": config.Lineage(**{**lin.__dict__, "capture_forward": forward})}})
        run = qualify.Capture(cap, code, invoke.Result(status=status))
        with qualify.Canary() as canary:
            return qualify._locked_problems("codex", cfg, run, canary, None)

    def test_every_locked_capture_checks_transport_and_cli_success(self):
        ok = [{"method": "GET", "path": "/codex-up/models", "outcome": "forwarded:200"},
              {"method": "GET", "path": "/codex-up/responses", "outcome": "ws-refused"},
              {"method": "POST", "path": "/backend-api/codex/analytics-events/events", "outcome": "refused"}]
        self.assertEqual(self._locked(ok), [])
        self.assertTrue(self._locked([*ok, {"method": "POST", "path": "/backend-api/ps/mcp", "outcome": "refused"}]))
        self.assertTrue(self._locked([{"method": "GET", "path": "/codex-up/models", "outcome": "forwarded:500"}]))
        self.assertTrue(self._locked(ok, code=1))
        self.assertTrue(self._locked(ok, status="failed"))


if __name__ == "__main__":
    unittest.main()
