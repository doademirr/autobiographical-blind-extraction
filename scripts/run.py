#!/usr/bin/env python3
"""Blind, two-lineage trait extraction from a diary or autobiography. See README.md and ARCHITECTURE.md.

Exit codes: 0 stage done · 1 a reliability gate fired · 2 usage or preflight failure ·
3 isolation or leak failure · 4 integrity failure · 5 a model call failed (rerun resumes).
"""

import argparse
import importlib
import json
import pkgutil
import re
import subprocess
import sys
import traceback
from pathlib import Path
from types import MappingProxyType

sys.path.insert(0, str(Path(__file__).resolve().parent))

import abx
from abx import invoke, lifecycle, store
from abx.errors import AbxError

UNEXPECTED = 70
NEXT_TEXT = MappingProxyType({
    "review_config": "review config.json, then run `prepare`",
    "approve_review_files": "edit and approve prepare/redactions.json and prepare/eras.json, then run `prepare`",
    "prepare": "run `prepare` (first approve prepare/redactions.json and prepare/eras.json)",
    "calibration_failed": "zoning calibration failed (prepare/calibration.json); no real run is permitted on this "
                          "zoner",
    "approve_spot_check": "read prepare/spot-check.json, mark any sentence wrongly kept or removed, set "
                          "\"approved\": true, then `seal` (if not done) and `freeze`",
    "seal": "fill in sealed/self-prediction.md and sealed/ipip-120.csv in your own editor, then run `seal`",
    "freeze": "run `freeze`", "extract": "run `extract`", "unmask": "run `unmask`",
    "done": "done: read report/report.md",
})


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def _show(out: lifecycle.CliResult) -> int:
    summary = out.summary
    if "next" in summary:
        summary = {**summary, "next": NEXT_TEXT[summary["next"]]}
    _print(summary)
    return out.exit_code


def _discover() -> dict[str, lifecycle.Stage]:
    """Every workspace command a module of the package declares as `STAGE`, in lifecycle order."""
    found = []
    for info in pkgutil.iter_modules(abx.__path__):
        stage = getattr(importlib.import_module(f"abx.{info.name}"), "STAGE", None)
        if isinstance(stage, lifecycle.Stage):
            found.append(stage)
    return {s.name: s for s in sorted(found, key=lambda s: s.order)}


STAGES = MappingProxyType(_discover())


REPO = Path(__file__).resolve().parent.parent


def _version() -> str:
    """`X.Y.Z (<short-sha>)`: the package version and the checkout's commit, `unknown` outside a git checkout."""
    found = re.search(r'^version = "([^"]+)"', (REPO / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    try:
        sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, check=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = "unknown"
    return f"{found.group(1) if found else 'unknown'} ({sha or 'unknown'})"


class _Version(argparse.Action):
    """Looks the version up only when asked, so ordinary runs never spawn git."""

    def __call__(self, parser, namespace, values, option_string=None):
        print(_version())
        parser.exit()


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="run.py", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--version", action=_Version, nargs=0, help="print the harness version and commit, then exit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for stage in STAGES.values():
        cmd = sub.add_parser(stage.name, help=stage.help)
        cmd.add_argument("ws", type=Path)
        for arg in stage.args:
            cmd.add_argument(*arg.flags, **arg.options)
    return ap


def _run_stage(stage: lifecycle.Stage, args: argparse.Namespace) -> int:
    if stage.creates_workspace:
        return _show(stage.run(args.ws, args))
    ws = store.Workspace(args.ws.resolve())
    store.verify_manifest(ws)  # integrity first: nothing below may read a frozen file that was edited or removed
    if not ws.path("config.json").exists():
        print(f"{args.ws} is not a workspace (no config.json)", file=sys.stderr)
        return 2
    if stage.checks_method:
        invoke.check_method(ws)  # an older workspace's config may not parse under the current method's rules
    if stage.estimate and ws.path("prepare/eras.json").exists():
        pre = stage.estimate(ws)
        extra = f" (+{pre.conditional_calls} conditional)" if pre.conditional_calls else ""
        print(f"{stage.name}: about {pre.model_calls} model calls{extra}: {pre.note}; an output that fails "
              f"validation is resampled, up to {invoke.MAX_ATTEMPTS} attempts per call", file=sys.stderr)
    return _show(stage.run(ws, args))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run_stage(STAGES[args.cmd], args)
    except AbxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception:  # an unexpected crash must not exit 1, which means "gate fired"
        traceback.print_exc()
        return UNEXPECTED


if __name__ == "__main__":
    sys.exit(main())
