"""`status`: where a workspace stands and what to run next. Reads files only; never opens sealed/."""

from . import store

STEPS = [
    ("prepare/stats.json", "prepare", "approve prepare/redactions.json and prepare/eras.json, then run `prepare`"),
    ("prereg/sealed-hashes.json", "seal", "fill in sealed/self-prediction.md and sealed/ipip-120.csv, then `seal`"),
]


def status(ws: store.Workspace) -> dict:
    gens = sorted(store.frozen_generations(ws))
    calls: dict[str, int] = {}
    for path in ws.root.glob("run/calls/*/*/*.json"):
        stage = path.parent.parent.name
        calls[stage] = calls.get(stage, 0) + 1
    incidents = [ws.rel(p) for p in sorted(ws.root.glob("run/incidents/**/*.json"))]
    nxt = next((todo for rel, _, todo in STEPS if not ws.path(rel).exists()), None)
    if nxt is None:
        nxt = ("run `freeze`" if "A" not in gens else "run `extract`" if "C" not in gens
               else "run `unmask`" if "E" not in gens else "done: read report/report.md")
    return {"generations": gens, "calls": calls, "incidents": incidents, "next": nxt}
