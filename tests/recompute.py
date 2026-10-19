"""Rebuild every report figure from a finished workspace's raw files, independently of `unmask.compute`.

Shared by the offline smoke (`test_end_to_end`) and the live smoke (`live_smoke.sh`). Corpus
statistics come from the text units and zoning labels, agreement from the raw ratings, comparisons
from the sealed inputs and crosswalk codes. The rebuilt results must equal `results.json` field by
field, and `report.md` must equal the report rendered from them, so every number is checked in its
own row.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from abx import agreement, config, extract, invoke, ipip, report, seal, store, unmask
from abx.errors import AbxError

__all__ = ["compare", "expected", "problems"]


def _corpus(ws: store.Workspace) -> dict:
    redacted = ws.path("prepare/redacted.txt").read_text(encoding="utf-8")
    sentences = store.read_json(ws.path("prepare/sentences.json"))
    stats = {}
    for era in store.read_json(ws.path("prepare/eras.json"))["eras"]:
        labels = store.read_json(ws.path(f"prepare/zoning/{era['id']}.json"))
        mine = [s for s in sentences if s["segment_id"] in set(era["segment_ids"])]
        words = {s["id"]: len(redacted[s["start"]:s["end"]].split()) for s in mine}
        total = sum(words.values())
        kept = sum(n for sid, n in words.items() if labels[sid] == "keep")
        ratio = kept / total if total else 0.0
        stats[era["id"]] = {"sentences": len(mine), "segments": len(era["segment_ids"]), "words": total,
                            "kept_words": kept, "kept_ratio": ratio,
                            "mixed": sum(1 for lab in labels.values() if lab == "mixed"),
                            "removed": sum(1 for lab in labels.values() if lab == "remove"),
                            "band": "normal" if ratio >= 0.5 else "thin" if ratio >= 0.25 else "stop"}
    return stats


def _arm(arm: agreement.ArmResult) -> dict:
    return {"metric": arm.metric, "alpha": arm.alpha, "verdict": arm.verdict, "reason": arm.reason,
            "paired_fraction": arm.paired_fraction, "raw_agreement": arm.raw_agreement,
            "missing_rate": arm.missing_rate, "stability": dict(sorted(arm.stability.items())),
            "units": len(arm.units), "integrity_audit_due": arm.integrity_audit_due}


def expected(ws: store.Workspace) -> dict:
    """The results `unmask` must have produced, rebuilt from raw ratings and sealed inputs."""
    cfg = config.load(ws)
    book = store.read_json(ws.path("run/codebook/codebook.json"))
    eras = [e["id"] for e in store.read_json(ws.path("prepare/eras.json"))["eras"]]
    instrument = ipip.load_instrument(ws)
    inductive, deductive_arm = extract.arms(extract.load_ratings(ws), book, eras, list(instrument["facets"]))
    ratings = extract.load_ratings(ws)
    lineages = sorted(inductive.collapsed)
    status = {c["id"]: {e: agreement.status([inductive.collapsed[lin][extract.Unit(c["item_id"], e)]
                                            for lin in lineages]) for e in eras} for c in book["constructs"]}
    collapsed = [{"lineage": lin, "facet": f, "value": v}
                 for lin in sorted(deductive_arm.collapsed) for f, v in deductive_arm.collapsed[lin].items()]
    self_report = ipip.score(ipip.parse_responses(ws.path("sealed/ipip-120.csv").read_text(), instrument), instrument)
    inductive_ok = inductive.verdict in unmask.REPORTABLE
    supported = {cid for cid, by_era in status.items() if "supported" in by_era.values()}
    codes = {c: store.read_json(ws.path(f"run/crosswalk/codes-{c}.json"))["codes"] for c in cfg.crosswalk_coders}
    preds = list(seal.predictions(ws.path("sealed/self-prediction.md").read_text()))
    stored_audit = store.read_json(ws.path("run/agreement.json")).get("integrity_audit")
    return {
        "corpus": _corpus(ws),
        "fingerprints": {lin: {k: v for k, v in q.items() if k != "evidence"}
                         for lin, q in store.read_json(ws.path(invoke.QUALIFICATION_A)).items()},
        "agreement": {"inductive": _arm(inductive), "deductive": _arm(deductive_arm),
                      "downgrades": sum(1 for rows in ratings.verdicts.values() for v in rows if v["downgrade"]),
                      "integrity_audit": stored_audit},
        "constructs": [{"id": c["id"], "name": c["name"], "definition": c["definition"], "lineages": c["lineages"],
                        "status": status[c["id"]]} for c in book["constructs"]],
        "predictions": unmask.prediction_rates(codes, preds, supported if inductive_ok else set())
        | {"inductive_reportable": inductive_ok},
        "deductive_vs_ipip": unmask.domain_comparison(unmask.deductive_domains(collapsed, instrument), self_report)
        | {"deductive_reportable": deductive_arm.verdict in unmask.REPORTABLE},
        "domain_names": instrument["domains"],
    }


def _diff(got, want, path="") -> list[str]:
    if isinstance(want, dict) and isinstance(got, dict):
        out = [f"{path}.{k}: missing" for k in want if k not in got]
        out += [f"{path}.{k}: unexpected" for k in got if k not in want]
        return out + [d for k in want if k in got for d in _diff(got[k], want[k], f"{path}.{k}")]
    if isinstance(want, list) and isinstance(got, list) and len(got) == len(want):
        return [d for i, (g, w) in enumerate(zip(got, want, strict=True)) for d in _diff(g, w, f"{path}[{i}]")]
    return [] if got == want else [f"{path}: reported {got!r}, recomputed {want!r}"]


def compare(results: dict, report_md: str, want: dict) -> list[str]:
    """Field-by-field differences, then any line of report.md that differs from the rebuilt report."""
    plain = json.loads(json.dumps(want))
    out = _diff(results, plain)
    rendered = report.render(plain).splitlines()
    actual = report_md.splitlines()
    out += [f"report.md line {i + 1} differs from its recomputation" for i in range(max(len(rendered), len(actual)))
            if (rendered[i] if i < len(rendered) else None) != (actual[i] if i < len(actual) else None)]
    return out


def problems(ws: store.Workspace) -> list[str]:
    try:
        gens = [e["gen"] for e in store.verify_manifest(ws)]
    except AbxError as exc:
        return [f"manifest: {exc}"]
    out = [] if gens == ["A", "B", "C", "D", "E"] else [f"generations {gens}"]
    report_md = ws.path("report/report.md").read_text()
    if [h for h in report_md.splitlines() if h.startswith("## ")][:1] != ["## This is not a clinical assessment"]:
        out.append("report's first section is not the non-clinical statement")
    return out + compare(store.read_json(ws.path("report/results.json")), report_md, expected(ws))


if __name__ == "__main__":
    found = problems(store.Workspace(Path(sys.argv[1]).resolve()))
    print("\n".join(found) or "every report figure recomputes")
    sys.exit(1 if found else 0)
