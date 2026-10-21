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

# 1. The pipeline, with production qualification (real logins, metadata reads forwarded, inference captured).
stage init "$WS" --text "$FIX/autobiography.txt" --canary ABXPROFILECANARY
stage prepare "$WS"
# Live raters know Franklin's text and restore redacted names from memory ("Samuel K." -> Keimer), which the
# prompt audit then stops. Redaction is covered offline; the live run approves an empty list.
cp "$FIX/eras.json" "$WS/prepare/"
printf '{"approved": true, "names": {}}\n' > "$WS/prepare/redactions.json"
stage prepare "$WS"
# A developer smoke test on a public fixture approves its own spot check, as it does the redaction list above; a real
# run never does: the user reads and marks it.
python3 - "$WS/prepare/spot-check.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
json.dump({**doc, "approved": True}, open(sys.argv[1], "w"), indent=1)
PY
cp "$FIX/self-prediction.md" "$FIX/ipip-120.csv" "$WS/sealed/"
stage seal "$WS"

# 2. The leak probe's own positive control, through the same recorded probe path: a rater handed an
#    instruction file holding a canary must report it, so the NONEs above mean something.
python3 - "$REPO" "$WS" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1] + "/scripts")
from abx import config, qualify, store
ws = store.Workspace(__import__("pathlib").Path(sys.argv[2]))
cfg = config.load(ws)
print(json.dumps({lin: qualify.leak_control(ws, cfg, lin) for lin in cfg.lineages}, indent=1))
PY

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
