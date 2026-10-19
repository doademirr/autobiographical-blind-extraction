"""Shared fixtures: a config that points at the fake CLIs, and a scratch workspace."""

import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from abx import init, invoke, store

from . import REPO

FAKES = REPO / "tests" / "fakes"
FAKE_ENV = ["ABX_FAKE_LOG", "ABX_FAKE_VERSION", "ABX_FAKE_TOOL_EVENT", "ABX_FAKE_FAIL", "ABX_FAKE_LEAK",
            "ABX_FAKE_FAIL_AFTER", "ABX_FAKE_RAW", "ABX_FAKE_CAPTURE_EXTRA_TOOL", "ABX_FAKE_CAPTURE_RESULT"]


def fake_config(auth_file: Path) -> dict:
    return {
        "lineages": {
            "claude": {"cli": str(FAKES / "claude"), "model": "fake-claude-1",
                       "input_budget_tokens": 200000, "reserve_output_tokens": 8000,
                       "locked_read_result": init.CLAUDE_LOCKED_READ},
            "codex": {"cli": str(FAKES / "codex"), "model": "fake-codex-1",
                      "input_budget_tokens": 200000, "reserve_output_tokens": 8000,
                      "sandbox_exec": str(FAKES / "sandbox-exec"), "sandbox_allow": [str(FAKES)],
                      "auth_file": str(auth_file), "disable": init.CODEX_DISABLE, "config": init.CODEX_CONFIG,
                      "retained_tools": init.CODEX_RETAINED, "capture_forward": False},
        },
        "runs": 3,
        "roles": {"zoner": "claude", "codebook_author": "claude", "crosswalk_coders": ["claude", "codex"]},
        "canaries": ["ABXPROFILECANARY"],
        "env_passthrough": FAKE_ENV,
        "timeout_s": 60,
    }


class FakeWorkspace:
    """A temp workspace with the repo's schemas frozen under prereg/, plus a fake log dir."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="abx-test-")
        root = Path(os.path.realpath(self._tmp.name))
        self.ws = store.Workspace(root / "ws")
        shutil.copytree(REPO / "schemas", self.ws.path("prereg/schemas"))
        self.log = root / "fakelog"
        auth = root / "auth.json"
        auth.write_text("{}")
        self.cfg = fake_config(auth)
        self._env = mock.patch.dict(os.environ, {"ABX_FAKE_LOG": str(self.log)})
        self._env.start()

    def qualified(self) -> dict:
        return {lin: {**invoke.live_fingerprint(self.cfg, lin), "resolved_model": self.cfg["lineages"][lin]["model"]}
                for lin in self.cfg["lineages"]}

    def prompts_logged(self) -> list[str]:
        path = self.log / "prompts.jsonl"
        return path.read_text().splitlines() if path.exists() else []

    def close(self):
        self._env.stop()
        self._tmp.cleanup()
