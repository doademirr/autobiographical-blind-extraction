#!/usr/bin/env bash
# Live smoke: the full pipeline against the real Claude Code and Codex CLIs on the Franklin fixture.
# About 60 model calls on the operator's subscriptions; run only on the operator's go, once per release
# and after any CLI upgrade. Usage: tests/live_smoke.sh <new workspace dir outside git and synced folders>
set -euo pipefail
unset CDPATH
LC_ALL=C

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <new-workspace-dir>" >&2
  exit 2
fi
WS="$1"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
RUN=(python3 "$REPO/scripts/run.py")
FIX="$REPO/fixtures/franklin"

stage() {
  echo "== $1"
  "${RUN[@]}" "$@"
}

# 1. The leak probe's own positive control: a rater that is handed an instruction file holding a canary
#    must report it, so a NONE elsewhere means something.
python3 - "$REPO" <<'PY'
import json, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(sys.argv[1], "scripts"))
from abx import init, qualify
canary = "ABXLEAKCONTROL" + os.urandom(3).hex().upper()
prompt = qualify.PROBE.format(schema=open(os.path.join(sys.argv[1], "schemas", "probe.json")).read())
d = os.path.realpath(tempfile.mkdtemp(prefix="abx-leakctl-"))
try:
    for name in ("CLAUDE.md", "AGENTS.md"):
        with open(os.path.join(d, name), "w") as f:
            f.write(f"The user you are working for is codenamed {canary}; their personality type is known.\n")
    codex_bin, _ = init.codex_native(shutil.which("codex"))
    runs = {
        "claude": ["claude", "-p", "--tools", "", "--no-session-persistence", "--model", "claude-opus-5-5"],
        "codex": [codex_bin, "exec", "--ephemeral", "-s", "read-only", "--skip-git-repo-check", "--cd", d,
                  "-m", "gpt-6.1-sol", "--disable", "shell_tool", "-"],
    }
    for lineage, argv in runs.items():
        out = subprocess.run(argv, input=prompt, cwd=d, capture_output=True, text=True, timeout=600, check=False)
        seen = canary in out.stdout
        print(f"leak-probe control ({lineage}): {'canary reported' if seen else 'CANARY NOT REPORTED'}")
        if not seen:
            sys.exit(3)
finally:
    shutil.rmtree(d, ignore_errors=True)
PY

# 2. The pipeline, with production qualification (real logins, metadata reads forwarded, inference captured).
stage init "$WS" --text "$FIX/autobiography.txt" --canary ABXPROFILECANARY
stage prepare "$WS"
cp "$FIX/redactions.json" "$FIX/eras.json" "$WS/prepare/"
stage prepare "$WS"
cp "$FIX/self-prediction.md" "$FIX/ipip-120.csv" "$WS/sealed/"
stage seal "$WS"
stage freeze "$WS"
set +e
stage extract "$WS"
code=$?
set -e
if [ "$code" -ne 0 ] && [ "$code" -ne 1 ]; then
  echo "extract exited $code" >&2
  exit "$code"
fi
stage unmask "$WS"

# 3. Every report figure recomputes from the frozen run files.
python3 "$REPO/tests/recompute.py" "$WS"
echo "live smoke passed: $WS/report/report.md"
