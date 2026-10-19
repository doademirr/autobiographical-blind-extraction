#!/usr/bin/env python3
"""Blind, two-lineage trait extraction from a diary or autobiography. See SPEC.md.

Exit codes: 0 stage done · 1 a reliability gate fired · 2 usage or preflight failure ·
3 isolation or leak failure · 4 integrity failure · 5 a model call failed (rerun resumes).
"""

import argparse
import importlib
import json
import pkgutil
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import abx
from abx import init, lifecycle, store
from abx.errors import AbxError

UNEXPECTED = 70
NEXT_TEXT = {
    "approve_review_files": "edit and approve prepare/redactions.json and prepare/eras.json, then run `prepare`",
    "prepare": "run `prepare` (first approve prepare/redactions.json and prepare/eras.json)",
    "seal": "fill in sealed/self-prediction.md and sealed/ipip-120.csv in your own editor, then run `seal`",
    "freeze": "run `freeze`", "extract": "run `extract`", "unmask": "run `unmask`",
    "done": "done: read report/report.md",
}


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def _show(out: dict) -> int:
    if "next" in out:
        out = {**out, "next": NEXT_TEXT[out["next"]]}
    _print(out)
    return 0


def _show_extract(result: dict) -> int:
    gates = {arm: result[arm]["verdict"] for arm in ("inductive", "deductive")}
    _print({"gates": gates, "alpha": {arm: result[arm]["alpha"] for arm in gates}})
    return 1 if "not_reportable" in gates.values() else 0


def _show_unmask(_: dict) -> int:
    _print({"report": "report/report.md"})
    return 0


SHOW = {"extract": _show_extract, "unmask": _show_unmask}


def _discover() -> dict[str, lifecycle.Stage]:
    """Every workspace command a module of the package declares as `STAGE`, in lifecycle order."""
    found = []
    for info in pkgutil.iter_modules(abx.__path__):
        stage = getattr(importlib.import_module(f"abx.{info.name}"), "STAGE", None)
        if isinstance(stage, lifecycle.Stage):
            found.append(stage)
    return {s.name: s for s in sorted(found, key=lambda s: s.order)}


STAGES = _discover()


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="run.py", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init", help="create a workspace from the text")
    p_init.add_argument("ws", type=Path)
    p_init.add_argument("--text", type=Path, nargs="+", required=True)
    p_init.add_argument("--canary", nargs="*", default=[], help="terms only your own profile would contain")
    p_init.add_argument("--allow-synced", action="store_true")
    for stage in STAGES.values():
        sub.add_parser(stage.name, help=stage.help).add_argument("ws", type=Path)
    p_rev = sub.add_parser("revise", help="authorised pre-unmask revision (not in this version)")
    p_rev.add_argument("ws", type=Path)
    p_rev.add_argument("artifact")
    return ap


def _run_stage(stage: lifecycle.Stage, ws: store.Workspace) -> int:
    if stage.estimate and ws.path("prepare/eras.json").exists():
        pre = stage.estimate(ws)
        extra = f" (+{pre.conditional_calls} conditional)" if pre.conditional_calls else ""
        print(f"{stage.name}: about {pre.model_calls} model calls{extra}: {pre.note}", file=sys.stderr)
    return SHOW.get(stage.name, _show)(stage.run(ws))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
        return _run_stage(STAGES[args.cmd], ws)
    except AbxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception:  # an unexpected crash must not exit 1, which means "gate fired"
        traceback.print_exc()
        return UNEXPECTED


if __name__ == "__main__":
    sys.exit(main())
