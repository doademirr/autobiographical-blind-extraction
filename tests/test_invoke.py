import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from abx import invoke, prompts, store
from abx.errors import CallFailed, IntegrityError, IsolationError, UsageError

from .fakes import fakelib
from .helpers import FakeWorkspace

ECHO = "# abx-role: echo\nanswer as JSON per schema\n"


def _spec(run=1, lineage="claude", text=ECHO, role="probe", era=None):
    prompt = prompts.Prompt(role, text, {"template:probe": store.sha256_text(text)})
    return invoke.CallSpec(stage="test", role=role, lineage=lineage, run=run, era=era, generation="A",
                           schema_name="probe", prompt=prompt)


class CallTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()
        self.ws, self.cfg = self.fw.ws, self.fw.cfg
        self.q = self.fw.qualified()

    def tearDown(self):
        self.fw.close()

    def call(self, spec):
        return invoke.call(self.ws, self.cfg, spec, self.q[spec.lineage])

    def test_success_records_and_returns_output(self):
        for lineage in ("claude", "codex"):
            out = self.call(_spec(lineage=lineage))
            self.assertEqual(out, {"answer": f"{lineage}:0"})
            rec = store.read_json(invoke.record_path(self.ws, _spec(lineage=lineage)))
            self.assertEqual(rec["input_artifacts"], {"template:probe": store.sha256_text(ECHO)})
            self.assertEqual(rec["fingerprint"]["resolved_model"], self.cfg["lineages"][lineage]["model"])

    def test_every_tool_event_kind_fails_closed(self):
        for lineage, kinds in fakelib.TOOL_EVENTS.items():
            for n, kind in enumerate(kinds, start=1):
                with self.subTest(lineage=lineage, kind=kind), \
                        mock.patch.dict(os.environ, {"ABX_FAKE_TOOL_EVENT": kind}):
                    spec = _spec(lineage=lineage, run=n)
                    with self.assertRaises(IsolationError) as cm:
                        self.call(spec)
                    self.assertEqual(cm.exception.exit_code, 3)
                    self.assertFalse(invoke.record_path(self.ws, spec).exists())
                    incident = store.read_json(self.ws.path(f"run/incidents/{spec.identity}.json"))
                    self.assertEqual(incident["kind"], "tool_event")

    def test_tool_event_outranks_cli_failure(self):
        with mock.patch.dict(os.environ, {"ABX_FAKE_TOOL_EVENT": "command_execution", "ABX_FAKE_FAIL": "1"}):
            with self.assertRaises(IsolationError):
                self.call(_spec(lineage="codex"))

    def test_cli_failure_and_invalid_output_exit_5(self):
        for env in ({"ABX_FAKE_FAIL": "1"}, {"ABX_FAKE_RAW": "not json"}, {"ABX_FAKE_RAW": '{"other": 1}'}):
            for lineage in ("claude", "codex"):
                with self.subTest(env=env, lineage=lineage), mock.patch.dict(os.environ, env):
                    with self.assertRaises(CallFailed) as cm:
                        self.call(_spec(lineage=lineage))
                    self.assertEqual(cm.exception.exit_code, 5)

    def test_replicates_run_separately_and_resume_reuses_each(self):
        for run in (1, 2, 3):
            self.call(_spec(run=run))
        self.assertEqual(len(self.fw.prompts_logged()), 3)
        outs = [self.call(_spec(run=run)) for run in (1, 2, 3)]
        self.assertEqual(len(self.fw.prompts_logged()), 3)
        self.assertEqual([o["answer"] for o in outs], ["claude:0", "claude:1", "claude:2"])

    def test_changed_input_reruns(self):
        self.call(_spec())
        self.call(_spec(text=ECHO + "more\n"))
        self.assertEqual(len(self.fw.prompts_logged()), 2)

    def test_fingerprint_change_is_integrity_failure(self):
        with mock.patch.dict(os.environ, {"ABX_FAKE_VERSION": "claude-fake 9.9.9"}):
            with self.assertRaises(IntegrityError) as cm:
                self.call(_spec())
        self.assertIn("cli_version", str(cm.exception))
        self.assertEqual(self.fw.prompts_logged(), [])

    def test_unexpected_claude_model_is_integrity_failure(self):
        self.q["claude"]["resolved_model"] = "some-other-model"
        with self.assertRaises(IntegrityError):
            self.call(_spec())

    def test_over_budget_is_refused_before_transmission(self):
        self.cfg["lineages"]["claude"]["input_budget_tokens"] = 100
        self.q = self.fw.qualified()
        with self.assertRaises(UsageError):
            self.call(_spec())
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
                          ("deductive_scorer", "ledger:codex:1:e1"), ("recode", "self_prediction:sealed")):
            with self.subTest(role=role, bad=bad), self.assertRaises(IsolationError):
                prompts.check_allowlist(role, [bad], rater=("claude", 1))

    def test_assemble_fills_slots_and_hashes_inputs(self):
        texts = {"template:probe": "# abx-role: probe\n{{q}} {{label}}", "probe:leak": "Q?"}
        p = prompts.assemble("probe", {"q": "probe:leak"}, texts.__getitem__, {"label": "x"})
        self.assertEqual(p.text, "# abx-role: probe\nQ? x")
        self.assertEqual(set(p.artifacts), {"template:probe", "probe:leak"})


class SubstringAuditTest(unittest.TestCase):
    SECRETS = prompts.Secrets(
        redacted_names=["Collins"], removed_sentences=["Looking back, I can see this was my pattern all along."],
        self_prediction=["P1: I will be found conscientious."], ipip=["i001,4"])

    def _p(self, role, text):
        return prompts.Prompt(role, text, {})

    def test_names_blocked_everywhere_including_zoning(self):
        with self.assertRaises(IsolationError):
            prompts.audit(self._p("zoner", "met Collins"), self.SECRETS)

    def test_removed_text_blocked_only_for_zoned_consumers(self):
        text = "x " + self.SECRETS.removed_sentences[0]
        prompts.audit(self._p("zoner", text), self.SECRETS)
        with self.assertRaises(IsolationError):
            prompts.audit(self._p("recode", text), self.SECRETS)

    def test_self_prediction_only_in_crosswalk_after_c(self):
        text = "P1: I will be found conscientious."
        prompts.audit(self._p("crosswalk", text), self.SECRETS, after_blind_results=True)
        with self.assertRaises(IsolationError):
            prompts.audit(self._p("crosswalk", text), self.SECRETS, after_blind_results=False)
        with self.assertRaises(IsolationError):
            prompts.audit(self._p("discovery", text), self.SECRETS, after_blind_results=True)

    def test_ipip_blocked_everywhere(self):
        with self.assertRaises(IsolationError):
            prompts.audit(self._p("crosswalk", "i001,4"), self.SECRETS, after_blind_results=True)


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
        self.assertTrue(str(self.tmp).startswith("/private/var/folders") or str(self.tmp).startswith("/private/tmp"))
        self.assertEqual(self.cat(self.allowed).stdout, "readable")

    def test_reads_outside_the_allowlist_are_denied(self):
        for directory in (Path.home(), Path("/opt/homebrew"), Path("/usr/local")):
            canary = self._canary(directory)
            if canary is None:
                continue
            with self.subTest(directory=directory):
                res = self.cat(canary)
                self.assertNotEqual(res.returncode, 0)
                self.assertNotIn("CANARY", res.stdout)

    def test_symlink_into_denied_path_is_denied(self):
        canary = self._canary(Path.home())
        link = Path(tempfile.gettempdir()) / f"abx-link-{os.getpid()}"
        link.symlink_to(canary)
        try:
            res = self.cat(link)
            self.assertNotIn("CANARY", res.stdout)
        finally:
            link.unlink()


class OutputParsingTest(unittest.TestCase):
    def test_codex_plain_log_lines_are_ignored_and_last_message_wins(self):
        lines = ["2026 WARN something", json.dumps({"type": "turn.started"}),
                 json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}),
                 json.dumps({"type": "error", "message": "Reconnecting... 1/5"}),
                 json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "second"}}),
                 json.dumps({"type": "turn.completed"})]
        out = invoke.parse_codex(lines)
        self.assertEqual((out.terminal, out.text, out.tool_events), ("success", "second", []))

    def test_claude_init_with_tools_is_a_tool_event(self):
        out = invoke.parse_claude([json.dumps({"type": "system", "subtype": "init", "tools": ["Read"],
                                               "mcp_servers": []})])
        self.assertTrue(out.tool_events)


if __name__ == "__main__":
    unittest.main()
