import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from abx import artifacts, invoke, prompts, store
from abx.errors import CallFailed, IntegrityError, IsolationError, UsageError
from abx.withheld import Withheld

from .fakes import fakelib
from .helpers import FakeWorkspace


def _req(run=1, lineage="claude"):
    return invoke.CallRequest(stage="test", role="probe", lineage=lineage, run=run, era=None, generation="A", slots={})


def _with(cfg: invoke.Config, **changes) -> invoke.Config:
    return invoke.Config(**{**cfg.__dict__, **changes})


class CallTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()
        self.ws, self.cfg = self.fw.ws, self.fw.config
        self.fw.qualify_stub()

    def tearDown(self):
        self.fw.close()

    def call(self, req, cfg=None):
        return invoke.call(self.ws, cfg or self.cfg, req)

    def test_success_records_inputs_and_events(self):
        for lineage in ("claude", "codex"):
            self.assertEqual(self.call(_req(lineage=lineage)), {"answer": "NONE"})
            rec = store.read_json(invoke.record_path(self.ws, _req(lineage=lineage)))
            self.assertEqual(set(rec["input_artifacts"]), {"template:probe", "schema:probe"})
            self.assertEqual(rec["fingerprint"]["resolved_model"], self.cfg.lineage(lineage).model)
            self.assertTrue(rec["events"])

    def test_every_tool_event_kind_fails_closed(self):
        for lineage, kinds in fakelib.TOOL_EVENTS.items():
            for n, kind in enumerate(kinds, start=1):
                with self.subTest(lineage=lineage, kind=kind), \
                        mock.patch.dict(os.environ, {"ABX_FAKE_TOOL_EVENT": kind}):
                    req = _req(lineage=lineage, run=n)
                    with self.assertRaises(IsolationError) as cm:
                        self.call(req)
                    self.assertEqual(cm.exception.exit_code, 3)
                    self.assertFalse(invoke.record_path(self.ws, req).exists())
                    incident = store.read_json(self.ws.path(f"run/incidents/{req.identity}.json"))
                    self.assertEqual(incident["kind"], "tool_event")

    def test_tool_event_outranks_cli_failure_and_timeout(self):
        for env in ({"ABX_FAKE_FAIL": "1"}, {"ABX_FAKE_SLEEP": "5"}):
            with self.subTest(env=env), mock.patch.dict(os.environ, {"ABX_FAKE_TOOL_EVENT": "mcp_tool_call", **env}):
                with self.assertRaises(IsolationError):
                    self.call(_req(lineage="codex"), _with(self.cfg, timeout_s=2))

    def test_cli_failure_timeout_and_invalid_output_exit_5(self):
        for env in ({"ABX_FAKE_FAIL": "1"}, {"ABX_FAKE_RAW": "not json"}, {"ABX_FAKE_RAW": '{"other": 1}'},
                    {"ABX_FAKE_SLEEP": "5"}):
            for lineage in ("claude", "codex"):
                with self.subTest(env=env, lineage=lineage), mock.patch.dict(os.environ, env):
                    with self.assertRaises(CallFailed) as cm:
                        self.call(_req(lineage=lineage), _with(self.cfg, timeout_s=2))
                    self.assertEqual(cm.exception.exit_code, 5)

    def test_replicates_run_separately_and_resume_reuses_each(self):
        for run in (1, 2, 3):
            self.call(_req(run=run))
        self.assertEqual(len(self.fw.prompts_logged()), 3)
        for run in (1, 2, 3):
            self.call(_req(run=run))
        self.assertEqual(len(self.fw.prompts_logged()), 3)

    def test_changed_input_reruns(self):
        self.call(_req())
        path = self.ws.path("prereg/prompts/probe.md")
        path.write_text(path.read_text() + "\nAlso answer briefly.\n")
        self.call(_req())
        self.assertEqual(len(self.fw.prompts_logged()), 2)

    def test_record_with_a_tool_event_is_never_reused(self):
        self.call(_req())
        path = invoke.record_path(self.ws, _req())
        rec = store.read_json(path)
        rec["events"].append({"type": "assistant", "detail": "tool_use", "tools": [], "mcp_servers": [],
                              "registry_present": True})
        store.write_json(path, rec)
        with self.assertRaises(IsolationError):
            self.call(_req())

    def test_a_record_copied_to_another_replicate_is_not_reused(self):
        self.call(_req(run=1))
        src, dst = invoke.record_path(self.ws, _req(run=1)), invoke.record_path(self.ws, _req(run=2))
        dst.write_text(src.read_text())
        self.call(_req(run=2))
        self.assertEqual(len(self.fw.prompts_logged()), 2)
        self.assertEqual(store.read_json(dst)["run"], 2)

    def test_artifact_reached_through_a_symlink_is_refused(self):
        era = self.ws.path("prepare/substrate/e1.md")
        era.parent.mkdir(parents=True)
        secret = self.ws.path("sealed/self-prediction.md")
        secret.parent.mkdir(parents=True)
        secret.write_text("P1: secret")
        era.symlink_to(secret)
        with self.assertRaises(UsageError):
            artifacts.path_of(self.ws, "era:e1")

    def test_fingerprint_change_is_integrity_failure(self):
        with mock.patch.dict(os.environ, {"ABX_FAKE_VERSION": "claude-fake 9.9.9"}):
            with self.assertRaises(IntegrityError) as cm:
                self.call(_req())
        self.assertIn("cli_version", str(cm.exception))
        self.assertEqual(self.fw.prompts_logged(), [])

    def test_unexpected_claude_model_is_integrity_failure(self):
        q = store.read_json(self.ws.path(invoke.QUALIFICATION))
        q["claude"]["resolved_model"] = "some-other-model"
        store.write_json(self.ws.path(invoke.QUALIFICATION), q)
        with self.assertRaises(IntegrityError):
            self.call(_req())

    def test_over_budget_is_refused_before_transmission(self):
        lin = self.cfg.lineage("claude")
        small = _with(self.cfg, lineages={**self.cfg.lineages,
                                          "claude": invoke.Lineage(**{**lin.__dict__, "input_budget_tokens": 100})})
        with self.assertRaises(UsageError):
            self.call(_req(), small)
        self.assertEqual(self.fw.prompts_logged(), [])


class AllowlistTest(unittest.TestCase):
    ORDER = ("e1", "e2", "e3")

    def test_discovery_gets_only_own_earlier_hypotheses(self):
        prompts.check_allowlist("discovery", ["era:e2", "hypotheses:claude:1:e1"], rater=("claude", 1),
                                era="e2", era_order=list(self.ORDER))
        for bad in ("hypotheses:codex:1:e1", "hypotheses:claude:2:e1", "hypotheses:claude:1:e2",
                    "hypotheses:claude:1:e3", "era:e3"):
            with self.subTest(bad=bad), self.assertRaises(IsolationError):
                prompts.check_allowlist("discovery", ["era:e2", bad], rater=("claude", 1), era="e2",
                                        era_order=list(self.ORDER))

    def test_deductive_never_gets_inductive_artifacts(self):
        for role, bad in (("deductive_ledger", "discovery:claude:1:e1"), ("deductive_ledger", "card:B"),
                          ("deductive_scorer", "ledger:codex:1:e1"), ("recode", "self_prediction:sealed"),
                          ("recode", "template:discovery")):
            with self.subTest(role=role, bad=bad), self.assertRaises(IsolationError):
                prompts.check_allowlist(role, [bad], rater=("claude", 1))

    def test_artifact_ids_cannot_escape_their_directory(self):
        for bad in ("era:../../sealed/self-prediction", "era:e1:extra", "discovery:claude:1", "card:A",
                    "ledger:claude:x:e1", "template:../x", "nokind:e1", "era:e1\n", "era:all", "run:1"):
            with self.subTest(bad=bad), self.assertRaises(UsageError):
                artifacts.parse(bad)
        with self.assertRaises(UsageError):
            prompts.check_allowlist("discovery", ["era:../../sealed/self-prediction"], era="e1")

    def test_labels_are_declared_short_and_single_line(self):
        texts = {"template:zoner": "# abx-role: zoner\n{{chunk}} {{era_label}}", "chunk:e1": "[s00001] x"}
        p = prompts.assemble("zoner", {"chunk": "chunk:e1"}, texts.__getitem__, {"era_label": "Boston"})
        self.assertEqual(p.text, "# abx-role: zoner\n[s00001] x Boston")
        for params in ({"era_label": "x\ny"}, {"era_label": "x" * 300}, {"secret": "x"}):
            with self.subTest(params=params), self.assertRaises(UsageError):
                prompts.assemble("zoner", {"chunk": "chunk:e1"}, texts.__getitem__, params)


class SubstringAuditTest(unittest.TestCase):
    WITHHELD = Withheld(
        redacted_names=["Collins"], removed_sentences=["Looking back, I can see this was my pattern all along."],
        self_prediction=["P1: I will be found conscientious."], ipip=["i001,4"])

    def _p(self, role, text):
        return prompts.Prompt(role, text, {})

    def test_names_blocked_everywhere_including_zoning(self):
        with self.assertRaises(IsolationError):
            prompts.audit(self._p("zoner", "met Collins"), self.WITHHELD)

    def test_removed_text_blocked_only_for_zoned_consumers(self):
        text = "x " + self.WITHHELD.removed_sentences[0]
        prompts.audit(self._p("zoner", text), self.WITHHELD)
        with self.assertRaises(IsolationError):
            prompts.audit(self._p("recode", text), self.WITHHELD)

    def test_self_prediction_only_in_crosswalk_after_c(self):
        text = "P1: I will be found conscientious."
        prompts.audit(self._p("crosswalk", text), self.WITHHELD, after_blind_results=True)
        with self.assertRaises(IsolationError):
            prompts.audit(self._p("crosswalk", text), self.WITHHELD, after_blind_results=False)
        with self.assertRaises(IsolationError):
            prompts.audit(self._p("discovery", text), self.WITHHELD, after_blind_results=True)

    def test_ipip_blocked_everywhere(self):
        with self.assertRaises(IsolationError):
            prompts.audit(self._p("crosswalk", "i001,4"), self.WITHHELD, after_blind_results=True)


@unittest.skipUnless(Path("/usr/bin/sandbox-exec").exists(), "macOS sandbox-exec required")
class SandboxProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="abx-sb-")))
        self.allowed = self.tmp / "cwd" / "ok.txt"
        self.allowed.parent.mkdir()
        self.allowed.write_text("readable")
        self.profile = self.tmp / "p.sb"
        self.profile.write_text(invoke.sandbox_profile([str(self.tmp)]))
        self.canaries: list[Path] = []

    def tearDown(self):
        for c in self.canaries:
            c.unlink(missing_ok=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cat(self, path) -> subprocess.CompletedProcess:
        return subprocess.run(["/usr/bin/sandbox-exec", "-f", str(self.profile), "/bin/cat", str(path)],
                              capture_output=True, text=True, timeout=30, check=False)

    def _canary(self, directory: Path) -> Path | None:
        try:
            fd, name = tempfile.mkstemp(prefix="abx-canary-", dir=directory)
        except OSError:
            return None
        os.write(fd, b"CANARY")
        os.close(fd)
        self.canaries.append(Path(name))
        return Path(name)

    def test_allowed_temp_dir_is_readable_under_denied_root(self):
        self.assertTrue(str(self.tmp).startswith(("/private/var/folders", "/private/tmp")))
        self.assertEqual(self.cat(self.allowed).stdout, "readable")

    def test_reads_outside_the_allowlist_are_denied(self):
        exercised = []
        for directory in (Path.home(), Path("/Users/Shared"), Path("/opt/homebrew"), Path("/usr/local")):
            canary = self._canary(directory)
            if canary is None:
                continue
            exercised.append(directory)
            with self.subTest(directory=directory):
                res = self.cat(canary)
                self.assertNotEqual(res.returncode, 0)
                self.assertNotIn("CANARY", res.stdout)
        self.assertGreaterEqual(len(exercised), 2, f"only {exercised} could hold a canary")

    def test_usr_local_is_not_a_runtime_root(self):
        text = self.profile.read_text()
        self.assertNotIn('(subpath "/usr")', text)
        self.assertNotIn("/usr/local", text)

    def test_symlink_into_denied_path_is_denied(self):
        canary = self._canary(Path.home())
        link = Path(tempfile.gettempdir()) / f"abx-link-{os.getpid()}"
        link.symlink_to(canary)
        try:
            self.assertNotIn("CANARY", self.cat(link).stdout)
        finally:
            link.unlink()


class OutputParsingTest(unittest.TestCase):
    def test_codex_plain_log_lines_are_ignored_and_last_message_wins(self):
        lines = ["2026-10-19T10:32:44.599315Z WARN something", json.dumps({"type": "turn.started"}),
                 json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}),
                 json.dumps({"type": "error", "message": "Reconnecting... 1/5"}),
                 json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "second"}}),
                 json.dumps({"type": "turn.completed"})]
        out = invoke.parse_codex(lines)
        self.assertEqual((out.status, out.text, invoke.audit_events("codex", out.events)), ("success", "second", []))

    def test_malformed_json_events_fail_closed(self):
        self.assertTrue(invoke.audit_events("codex", invoke.parse_codex(['{"type": "item.started", ']).events))
        self.assertTrue(invoke.audit_events("codex", invoke.parse_codex(['["not", "an", "event"]']).events))
        self.assertTrue(invoke.audit_events("claude", invoke.parse_claude(["not json"]).events))

    def test_claude_init_registry_must_be_present_and_empty(self):
        for init in ({"tools": ["Read"], "mcp_servers": []}, {"tools": [], "mcp_servers": ["x"]}, {}):
            with self.subTest(init=init):
                out = invoke.parse_claude([json.dumps({"type": "system", "subtype": "init", **init})])
                self.assertTrue(invoke.audit_events("claude", out.events))


if __name__ == "__main__":
    unittest.main()
