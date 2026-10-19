"""Recompute every report figure from a finished workspace's frozen files.

Shared by the offline smoke (`test_end_to_end`) and the live smoke (`live_smoke.sh`), so both
hold a run to the same standard: each reported number must equal its recomputation.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from abx import agreement, extract, ipip, seal, store, unmask


def problems(ws: store.Workspace) -> list[str]:
    out = []
    try:
        gens = [e["gen"] for e in store.verify_manifest(ws)]
    except Exception as exc:  # reported as a finding, not raised
        return [f"manifest: {exc}"]
    if gens != ["A", "B", "C", "D", "E"]:
        out.append(f"generations {gens}")
    results = store.read_json(ws.path("report/results.json"))
    report = ws.path("report/report.md").read_text()
    if [h for h in report.splitlines() if h.startswith("## ")][:1] != ["## This is not a clinical assessment"]:
        out.append("report's first section is not the non-clinical statement")

    r = extract.Run(ws)
    book = store.read_json(ws.path("run/codebook/codebook.json"))
    runs = {lin: {str(n): {} for n in r.runs} for lin in r.lineages}
    downgrades = 0
    for path in sorted(ws.root.glob("run/recode/*.json")):
        lineage, run, era = path.stem.split("-")
        for v in store.read_json(path):
            runs[lineage][run[1:]][f"{v['item_id']}@{era}"] = None if v["verdict"] == "insufficient" else v["verdict"]
            downgrades += bool(v["downgrade"])
    units = [f"{c['item_id']}@{e}" for c in book["constructs"] for e in r.era_ids]
    druns = {lin: {} for lin in r.lineages}
    for path in sorted(ws.root.glob("run/deductive/scores-*.json")):
        _, lineage, run = path.stem.split("-")
        druns[lineage][run[1:]] = {s["facet"]: s["score"] for s in store.read_json(path)["scores"]}
    arms = {"inductive": agreement.arm(runs, units, "nominal"),
            "deductive": agreement.arm(druns, extract.FACETS, "ordinal")}
    for name, arm in arms.items():
        if results["agreement"][name]["alpha"] != arm.alpha:
            out.append(f"{name} alpha {results['agreement'][name]['alpha']} != recomputed {arm.alpha}")
        if arm.alpha is not None and f"{arm.alpha:.3f}" not in report:
            out.append(f"{name} alpha {arm.alpha:.3f} missing from report.md")
    if results["agreement"]["downgrades"] != downgrades:
        out.append("downgrade count differs")

    agree = store.read_json(ws.path("run/agreement.json"))
    inst = ipip.load_instrument()
    self_report = ipip.score(ipip.parse_responses(ws.path("sealed/ipip-120.csv").read_text(), inst), inst)
    domains = unmask.domain_comparison(unmask.deductive_domains(agree["deductive_collapsed"], inst), self_report)
    if results["deductive_vs_ipip"]["domains"] != json.loads(json.dumps(domains["domains"])):
        out.append("deductive-vs-IPIP domain rows differ")
    coders = sorted(p.stem.removeprefix("codes-") for p in ws.root.glob("run/crosswalk/codes-*.json"))
    codes = {c: store.read_json(ws.path(f"run/crosswalk/codes-{c}.json")) for c in coders}
    supported = {cid for cid, eras in agree["construct_status"].items() if "supported" in eras.values()}
    eligible = supported if agree["inductive"]["verdict"] in unmask.REPORTABLE else set()
    preds = list(seal.predictions(ws.path("sealed/self-prediction.md").read_text()))
    rates = unmask.prediction_rates(codes, preds, eligible)
    for key in ("predictions_matched_rate", "supported_constructs_matched_rate", "coder_agreement"):
        if results["predictions"][key] != rates[key]:
            out.append(f"{key} differs")
        if rates[key] is not None and f"{rates[key]:.0%}" not in report:
            out.append(f"{key} {rates[key]:.0%} missing from report.md")
    return out


if __name__ == "__main__":
    found = problems(store.Workspace(Path(sys.argv[1]).resolve()))
    print("\n".join(found) or "every report figure recomputes")
    sys.exit(1 if found else 0)
