"""Recompute every report figure from a finished workspace's raw run files.

Shared by the offline smoke (`test_end_to_end`) and the live smoke (`live_smoke.sh`), so both
hold a run to the same standard. Collapses are rebuilt from the raw ratings, not read from the
stored agreement, and every numeric field of `results.json` is compared, then looked for in
`report.md` as the report formats it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from abx import config, extract, freeze, ipip, report, seal, store, unmask
from abx.errors import AbxError

ARM_FIELDS = ("alpha", "verdict", "reason", "paired_fraction", "raw_agreement", "missing_rate", "stability", "units")


def expected(ws: store.Workspace) -> dict:
    """The figures `results.json` must hold, rebuilt from raw ratings and sealed inputs."""
    cfg = config.load(ws)
    book = store.read_json(ws.path("run/codebook/codebook.json"))
    eras = [e["id"] for e in store.read_json(ws.path("prepare/eras.json"))["eras"]]
    instrument = ipip.load_instrument(ws)
    ratings = extract.load_ratings(ws)
    inductive, deductive_arm = extract.arms(ratings, book, eras, list(instrument["facets"]))
    lineages = sorted(inductive.collapsed)
    status = {c["id"]: {e: extract.agreement.status([inductive.collapsed[lin][extract.Unit(c["item_id"], e)]
                                                     for lin in lineages]) for e in eras} for c in book["constructs"]}
    collapsed = [{"lineage": lin, "facet": f, "value": v}
                 for lin in sorted(deductive_arm.collapsed) for f, v in deductive_arm.collapsed[lin].items()]
    self_report = ipip.score(ipip.parse_responses(ws.path("sealed/ipip-120.csv").read_text(), instrument), instrument)
    supported = {cid for cid, by_era in status.items() if "supported" in by_era.values()}
    eligible = supported if inductive.verdict in unmask.REPORTABLE else set()
    codes = {c: store.read_json(ws.path(f"run/crosswalk/codes-{c}.json"))["codes"] for c in cfg.crosswalk_coders}
    preds = list(seal.predictions(ws.path("sealed/self-prediction.md").read_text()))
    return {
        "arms": {"inductive": inductive, "deductive": deductive_arm},
        "downgrades": sum(1 for rows in ratings.verdicts.values() for v in rows if v["downgrade"]),
        "status": status,
        "predictions": unmask.prediction_rates(codes, preds, eligible),
        "domains": unmask.domain_comparison(unmask.deductive_domains(collapsed, instrument), self_report),
        "corpus": store.read_json(ws.path("prepare/stats.json")),
        "fingerprints": store.read_json(ws.path(freeze.QUALIFICATION_A)),
    }


def compare(results: dict, report_md: str, exp: dict) -> list[str]:
    out = []
    for name, arm in exp["arms"].items():
        got = results["agreement"][name]
        want = {"alpha": arm.alpha, "verdict": arm.verdict, "reason": arm.reason,
                "paired_fraction": arm.paired_fraction, "raw_agreement": arm.raw_agreement,
                "missing_rate": arm.missing_rate, "stability": dict(sorted(arm.stability.items())),
                "units": len(arm.units)}
        out += [f"{name}.{k}: reported {got.get(k)!r}, recomputed {want[k]!r}" for k in ARM_FIELDS
                if got.get(k) != want[k]]
        for figure in (report.num(arm.alpha), report.pct(arm.paired_fraction), report.pct(arm.raw_agreement),
                       report.pct(arm.missing_rate), *(report.num(v) for v in arm.stability.values())):
            if figure not in report_md:
                out.append(f"{name}: {figure} missing from report.md")
    if results["agreement"]["downgrades"] != exp["downgrades"]:
        out.append("downgrade count differs")
    if {c["id"]: c["status"] for c in results["constructs"]} != exp["status"]:
        out.append("construct statuses differ")
    for key, value in exp["predictions"].items():
        if results["predictions"].get(key) != value:
            out.append(f"predictions.{key} differs")
    for key in ("predictions_matched_rate", "supported_constructs_matched_rate", "coder_agreement"):
        if exp["predictions"][key] is not None and report.pct(exp["predictions"][key]) not in report_md:
            out.append(f"predictions.{key} missing from report.md")
    got_dom = results["deductive_vs_ipip"]
    for key in ("domains", "compared", "agreement_rate"):
        if got_dom[key] != exp["domains"][key]:
            out.append(f"deductive_vs_ipip.{key} differs")
    for row in exp["domains"]["domains"].values():
        for v in (row["observer"], row["ipip"]):
            if v is not None and report.num(v, 2) not in report_md:
                out.append(f"domain figure {report.num(v, 2)} missing from report.md")
    if report.pct(exp["domains"]["agreement_rate"]) not in report_md:
        out.append("domain agreement rate missing from report.md")
    if results["corpus"] != exp["corpus"]:
        out.append("corpus statistics differ from the frozen preparation statistics")
    for era, s in exp["corpus"].items():
        if f"Era {era}: {s['sentences']} sentences" not in report_md or report.pct(s["kept_ratio"]) not in report_md:
            out.append(f"corpus figures for {era} missing from report.md")
    for lin, fp in exp["fingerprints"].items():
        if results["fingerprints"][lin] != {k: v for k, v in fp.items() if k != "evidence"}:
            out.append(f"{lin} fingerprint differs from the frozen qualification")
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
