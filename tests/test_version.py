import contextlib
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from abx import invoke

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import run as cli  # noqa: E402


def pyproject_version() -> str:
    return re.search(r'^version = "([^"]+)"', (REPO / "pyproject.toml").read_text(), re.M).group(1)


class VersionTest(unittest.TestCase):
    def test_prints_the_package_version_and_this_checkouts_commit_from_anywhere(self):
        sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
        with tempfile.TemporaryDirectory() as elsewhere:
            p = subprocess.run([sys.executable, str(REPO / "scripts" / "run.py"), "--version"], cwd=elsewhere,
                               capture_output=True, text=True, check=False)
        self.assertEqual((p.returncode, p.stdout.strip()), (0, f"{pyproject_version()} ({sha})"))

    def test_no_stage_or_model_call_runs(self):
        with mock.patch.object(cli, "_run_stage", side_effect=AssertionError("stage")), \
                mock.patch.object(invoke, "call", side_effect=AssertionError("call")), \
                contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as cm:
            cli.main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertTrue(out.getvalue().startswith(pyproject_version() + " ("))

    def test_git_failing_or_missing_gives_unknown(self):
        for failure in (subprocess.CalledProcessError(128, "git"), FileNotFoundError("git")):
            with self.subTest(failure=type(failure).__name__), \
                    mock.patch.object(cli.subprocess, "run", side_effect=failure):
                self.assertEqual(cli._version(), f"{pyproject_version()} (unknown)")


if __name__ == "__main__":
    unittest.main()
