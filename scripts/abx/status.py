"""`status`: where a workspace stands and the next step, as a code the CLI renders. Never opens sealed/."""

from . import calibration, lifecycle, spotcheck, store

__all__ = ["STAGE", "status"]


def status(ws: store.Workspace) -> dict:
    gens = sorted(store.frozen_generations(ws))
    calls: dict[str, int] = {}
    for path in ws.root.glob("run/calls/*/*/*.json"):
        calls[path.parent.parent.name] = calls.get(path.parent.parent.name, 0) + 1
    if not ws.path("prepare/stats.json").exists() or not ws.path(calibration.PATH).exists():
        nxt = "prepare"
    elif not store.read_json(ws.path(calibration.PATH))["passed"]:
        nxt = "calibration_failed"
    elif "A" not in gens and not spotcheck.approved(ws):
        nxt = "approve_spot_check"
    elif not ws.path(lifecycle.HASHES).exists():
        nxt = "seal"
    else:
        nxt = next((stage for gen, stage in (("A", "freeze"), ("C", "extract"), ("E", "unmask")) if gen not in gens),
                   "done")
    return {"generations": gens, "calls": calls,
            "incidents": [ws.rel(p) for p in sorted(ws.root.glob("run/incidents/**/*.json"))], "next": nxt}


STAGE = lifecycle.Stage("status", 6, "where the workspace stands", lifecycle.returns(status))
