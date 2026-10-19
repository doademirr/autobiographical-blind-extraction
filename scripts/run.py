#!/usr/bin/env python3
"""Blind, two-lineage trait extraction from a diary or autobiography. See SPEC.md.

Exit codes: 0 stage done · 1 a reliability gate fired · 2 usage or preflight failure ·
3 isolation or leak failure · 4 integrity failure · 5 a model call failed (rerun resumes).
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from abx import extract, freeze, init, prepare, seal, status, store, unmask
from abx.errors import AbxError

UNEXPECTED = 70


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run.py", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init", help="create a workspace from the text")
    p_init.add_argument("ws", type=Path)
    p_init.add_argument("--text", type=Path, nargs="+", required=True)
    p_init.add_argument("--canary", nargs="*", default=[], help="terms only your own profile would contain")
    p_init.add_argument("--allow-synced", action="store_true")
    for name, text in (("prepare", "redaction and eras review, qualification, zoning"),
                       ("seal", "check and hash sealed/"), ("freeze", "pre-register generation A"),
                       ("extract", "the blind engine, to generation C"),
                       ("unmask", "crosswalk, IPIP reveal, report"), ("status", "where the workspace stands")):
        sub.add_parser(name, help=text).add_argument("ws", type=Path)
    p_rev = sub.add_parser("revise", help="authorised pre-unmask revision (not in this version)")
    p_rev.add_argument("ws", type=Path)
    p_rev.add_argument("artifact")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "init":
            ws = init.init(args.ws, args.text, args.canary, args.allow_synced)
            _print({"workspace": str(ws.root), "next": "review config.json, then run `prepare`"})
            return 0
        if args.cmd == "revise":
            print("revise is not in this version; start a new workspace to change a frozen artifact", file=sys.stderr)
            return 2
        ws = store.Workspace(args.ws.resolve())
        if not ws.path("config.json").exists():
            print(f"{args.ws} is not a workspace (no config.json)", file=sys.stderr)
            return 2
        if args.cmd == "extract":
            result = extract.extract(ws)
            gates = {arm: result[arm]["verdict"] for arm in ("inductive", "deductive")}
            _print({"gates": gates, "alpha": {arm: result[arm]["alpha"] for arm in gates}})
            return 1 if "not_reportable" in gates.values() else 0
        if args.cmd == "unmask":
            unmask.unmask(ws)
            _print({"report": str(ws.path("report/report.md"))})
            return 0
        run = {"prepare": prepare.prepare, "seal": seal.seal, "freeze": freeze.freeze, "status": status.status}
        _print(run[args.cmd](ws))
        return 0
    except AbxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception:  # an unexpected crash must not exit 1, which means "gate fired"
        traceback.print_exc()
        return UNEXPECTED


if __name__ == "__main__":
    sys.exit(main())
