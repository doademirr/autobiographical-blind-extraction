import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from abx import init, prepare, qualify, store
from abx.errors import IsolationError, UsageError

from .helpers import FakeWorkspace

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "franklin"


def new_workspace(fw: FakeWorkspace) -> store.Workspace:
    root = fw.ws.root.parent / "w"
    return init.init(root, [FIXTURE / "autobiography.txt"], [], False, config=fw.cfg)


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
        original = ws.path("text/original.txt")
        self.assertFalse(original.stat().st_mode & stat.S_IWUSR)
        self.assertIn("Read(./sealed/**)", store.read_json(ws.path(".claude/settings.json"))["permissions"]["deny"])
        self.assertEqual(len(ws.path("sealed/ipip-120.csv").read_text().splitlines()), 121)
        self.assertTrue(ws.path("sealed/self-prediction.md").exists())

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
        self.assertFalse(self.ws.path("run/qualification.json").exists())

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
        q = store.read_json(self.ws.path("run/qualification.json"))
        self.assertEqual(q["codex"]["evidence"]["registry"], list(init.CODEX_RETAINED))
        self.assertEqual(q["claude"]["resolved_model"], "fake-claude-1")


class QualifyFailureTest(unittest.TestCase):
    def setUp(self):
        self.fw = FakeWorkspace()
        self.ws = new_workspace(self.fw)
        prepare.stage_method(self.ws)

    def tearDown(self):
        self.fw.close()

    def _qualify(self, env):
        with mock.patch.dict(os.environ, env):
            return qualify.qualify(self.ws, self.fw.cfg)

    def test_forbidden_tool_in_registry_fails(self):
        with self.assertRaises(IsolationError) as cm:
            self._qualify({"ABX_FAKE_CAPTURE_EXTRA_TOOL": "exec_command"})
        self.assertIn("functions.exec_command", str(cm.exception))

    def test_retained_tool_with_unpinned_result_fails(self):
        for result in ("ok", '{"accepted":true}'):
            with self.subTest(result=result), self.assertRaises(IsolationError):
                self._qualify({"ABX_FAKE_CAPTURE_RESULT": result})

    def test_leak_is_exit_3_and_cli_error_is_exit_2(self):
        with self.assertRaises(IsolationError) as cm:
            self._qualify({"ABX_FAKE_LEAK": "They are an ABXPROFILECANARY type."})
        self.assertEqual(cm.exception.exit_code, 3)
        with self.assertRaises(IsolationError):
            self._qualify({"ABX_FAKE_LEAK": "Some facts about them."})
        with self.assertRaises(UsageError) as cm:
            self._qualify({"ABX_FAKE_FAIL": "1"})
        self.assertEqual(cm.exception.exit_code, 2)

    def test_refused_discovery_fails_even_with_clean_registry(self):
        def problems(traffic):
            return qualify._transport_problems(type("Cap", (), {"traffic": traffic})())

        self.assertTrue(problems([{"method": "GET", "path": "/codex-up/models", "outcome": "forwarded:200"},
                                  {"method": "POST", "path": "/backend-api/ps/mcp", "outcome": "refused"}]))
        self.assertTrue(problems([{"method": "GET", "path": "/codex-up/models", "outcome": "forwarded:500"}]))
        clean = [{"method": "GET", "path": "/codex-up/models", "outcome": "forwarded:200"},
                 {"method": "GET", "path": "/codex-up/responses", "outcome": "ws-refused"},
                 {"method": "POST", "path": "/backend-api/codex/analytics-events/events", "outcome": "refused"}]
        self.assertEqual(problems(clean), [])


if __name__ == "__main__":
    unittest.main()
