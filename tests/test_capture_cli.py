"""Qualification's request capture against the real CLIs, model-free.

Codex uses the stand-in provider (no login, no network beyond loopback); Claude a dummy
API key. Skipped only when a CLI is not installed. The production-equivalent Codex
transport (real login, metadata reads forwarded to chatgpt.com) runs at `prepare`.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from abx import config, init, qualify

from .helpers import Logins, write_logins

PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "probe.md").read_text()
CLAUDE = os.path.realpath(shutil.which("claude")) if shutil.which("claude") else None  # pinned, as `init` does
CODEX = shutil.which("codex")


def real_config(logins: Logins) -> config.Config:
    codex_bin, codex_root = init.codex_native(CODEX) if CODEX else ("", "")
    lineages = {
        "claude": {"cli": CLAUDE, "model": "claude-opus-5-5", "input_budget_tokens": 1, "reserve_output_tokens": 0,
                   "locked_read_result": init.CLAUDE_LOCKED_READ, "profile_file": str(logins.claude_profile)},
        "codex": {"cli": codex_bin, "model": "gpt-6.1-sol", "input_budget_tokens": 1, "reserve_output_tokens": 0,
                  "sandbox_exec": "/usr/bin/sandbox-exec", "sandbox_allow": [codex_root],
                  "auth_file": str(logins.codex_auth),
                  "disable": list(init.CODEX_DISABLE), "config": list(init.CODEX_CONFIG),
                  "retained_tools": init.CODEX_RETAINED, "capture_forward": False},
    }
    roles = {"zoner": "claude", "codebook_author": "claude", "foil_author": "claude", "auditor": "codex",
             "facet_mapper": "codex", "crosswalk_coders": ["claude", "codex"]}
    return config.parse({"runs": 3, "roles": roles, "lineages": lineages, "canaries": ["ABXPROFILECANARY"],
                         "env_passthrough": [], "timeout_s": 120})


class RealCliCaptureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = real_config(write_logins(Path(self.tmp.name)))

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipUnless(CODEX and Path("/usr/bin/sandbox-exec").exists(), "codex and sandbox-exec required")
    def test_codex_locked_registry_retained_tools_and_positive_controls(self):
        with qualify.Canary() as canary:
            evidence = qualify.qualify_codex(self.cfg, canary, PROMPT)
        self.assertEqual(evidence["registry"], sorted(init.CODEX_RETAINED))
        self.assertEqual(evidence["positive_controls"], {"file": "canary returned", "mcp": "canary returned"})

    @unittest.skipUnless(CLAUDE, "claude required")
    def test_claude_empty_registry_refusal_and_positive_controls(self):
        with qualify.Canary() as canary:
            evidence = qualify.qualify_claude(self.cfg, canary, PROMPT)
        self.assertEqual(evidence["registry"], [])
        self.assertEqual(evidence["positive_controls"], {"file": "canary returned", "mcp": "canary returned"})

    def test_canary_dir_is_removed(self):
        with qualify.Canary() as canary:
            path = canary.dir
            self.assertTrue(path.exists())
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
