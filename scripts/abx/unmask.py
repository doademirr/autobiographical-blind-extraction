"""`unmask`: two-coder prediction crosswalk (generation D), then the IPIP reveal, comparisons
and report (generation E). Every figure is computed here or in `agreement`/`ipip`, never by a model.
"""

from statistics import median

from . import artifacts, invoke, ipip, prepare, prompts, qualify, report, seal, store
from .errors import IntegrityError, UsageError

REPORTABLE = {"report", "tentative"}
CODE_RANK = {"none": 0, "partial": 1, "match": 2}


def crosswalk(ws: store.Workspace, cfg: dict, book: dict) -> dict[str, list[dict]]:
    store.write_text_atomic(artifacts.path_of(ws, "constructs:all"), "".join(
        f"- {c['id']}: {c['name']}. {c['definition']}\n" for c in book["constructs"]))
    preds = seal.predictions(ws.path("sealed/self-prediction.md").read_text(encoding="utf-8"))
    pairs = {(p, c["id"]) for p in preds for c in book["constructs"]}
    secrets = prepare.load_secrets(ws)
    qual = qualify.qualified(ws)

    def validate(out) -> list[str]:
        got = [(x["prediction_id"], x["construct_id"]) for x in out["codes"]]
        return [] if len(got) == len(set(got)) and set(got) == pairs else ["codes must cover every pair exactly once"]

    codes = {}
    for lineage in cfg["roles"]["crosswalk_coders"]:
        prompt = prompts.assemble("crosswalk", {"constructs": "constructs:all", "predictions": "self_prediction:sealed",
                                                "schema": "schema:crosswalk"}, artifacts.resolver(ws))
        prompts.audit(prompt, secrets, after_blind_results=True)
        spec = invoke.CallSpec(stage="unmask", role="crosswalk", lineage=lineage, run=None, era=None, generation="D",
                               schema_name="crosswalk", prompt=prompt, validate=validate)
        codes[lineage] = invoke.call(ws, cfg, spec, qual[lineage])["codes"]
        store.write_json(ws.path(f"run/crosswalk/codes-{lineage}.json"), codes[lineage])
    return codes


def prediction_rates(codes: dict[str, list[dict]], predictions: list[str], eligible: set[str]) -> dict:
    """SPEC § Comparisons, inductive vs self-prediction.

    `eligible` is the supported constructs of a reportable inductive arm. A prediction is matched
    when every coder codes some eligible construct `match`, partial when every coder's best is
    `partial`; coders who disagree make it ambiguous, and it leaves both rates.
    """
    coders = sorted(codes)
    table = {coder: {(x["prediction_id"], x["construct_id"]): x["code"] for x in codes[coder]} for coder in coders}
    outcome = {}
    for p in predictions:
        best = {max((CODE_RANK[code] for (pid, cid), code in table[coder].items() if pid == p and cid in eligible),
                    default=0) for coder in coders}
        outcome[p] = ("unmatched", "partial", "matched")[best.pop()] if len(best) == 1 else "ambiguous"
    decided = [p for p in predictions if outcome[p] != "ambiguous"]
    matched = [p for p in decided if outcome[p] == "matched"]
    constructs_matched = sorted(c for c in eligible if any(
        all(table[coder].get((p, c)) == "match" for coder in coders) for p in predictions))
    pairs = set().union(*(table[c].keys() for c in coders)) if coders else set()
    return {
        "outcome": outcome, "matched": matched, "ambiguous": [p for p in predictions if outcome[p] == "ambiguous"],
        "predictions_decided": len(decided),
        "predictions_matched_rate": len(matched) / len(decided) if decided else None,
        "supported_eligible": len(eligible), "constructs_matched": constructs_matched,
        "supported_constructs_matched_rate": len(constructs_matched) / len(eligible) if eligible else None,
        "descriptive_matches": sorted({f"{pid}~{cid}" for coder in coders for (pid, cid), code in table[coder].items()
                                       if code == "match" and cid not in eligible}),
        "coder_agreement": (sum(1 for k in pairs if len({table[c].get(k) for c in coders}) == 1) / len(pairs))
        if pairs else None,
    }


def deductive_domains(collapsed: dict[str, dict[str, int | None]], instrument: dict) -> dict:
    """Facet = median of the lineage collapses (all present); domain = mean of >= 4 of 6 facets."""
    facets = {}
    for f in instrument["facets"]:
        vals = [collapsed[lin].get(f) for lin in sorted(collapsed)]
        facets[f] = median(vals) if vals and all(v is not None for v in vals) else None
    domains = {}
    for d in instrument["domains"]:
        present = [v for f, v in facets.items() if f.startswith(d) and v is not None]
        domains[d] = sum(present) / len(present) if len(present) >= ipip.DOMAIN_MIN_FACETS else None
    return {"facets": facets, "domains": domains}


def domain_comparison(observer: dict, self_report: dict) -> dict:
    rows = {}
    for d, obs in observer["domains"].items():
        o_band, s_band = ipip.observer_band(obs), ipip.ipip_band(self_report["domains"][d])
        rows[d] = {"observer": obs, "observer_band": o_band, "ipip": self_report["domains"][d], "ipip_band": s_band,
                   "same_band": (o_band == s_band) if o_band and s_band else None}
    compared = [r for r in rows.values() if r["same_band"] is not None]
    return {"domains": rows, "compared": len(compared),
            "agreement_rate": sum(r["same_band"] for r in compared) / len(compared) if compared else None}


def unmask(ws: store.Workspace) -> dict:
    store.verify_manifest(ws)
    seal.verify_sealed(ws)
    gens = store.frozen_generations(ws)
    if "C" not in gens:
        raise UsageError("blind results are not frozen; run `extract` first")
    if "E" in gens:
        raise IntegrityError("this workspace is already unmasked; start a new workspace for a new run")
    cfg = store.read_json(ws.path("config.json"))
    book = store.read_json(ws.path("run/codebook/codebook.json"))
    agree = store.read_json(ws.path("run/agreement.json"))
    if "D" not in gens:
        crosswalk(ws, cfg, book)
        store.append_generation(ws, "D", ["run/crosswalk/constructs.md",
                                          *(f"run/crosswalk/codes-{c}.json" for c in cfg["roles"]["crosswalk_coders"])])
    results = compute(ws, cfg, book, agree)
    store.write_json(ws.path("report/results.json"), results)
    store.write_text_atomic(ws.path("report/report.md"), report.render(results))
    store.append_generation(ws, "E", ["report/results.json", "report/report.md"])
    return results


def compute(ws: store.Workspace, cfg: dict, book: dict, agree: dict) -> dict:
    """Every reported figure, from frozen files only; the e2e test recomputes the same way."""
    codes = {c: store.read_json(ws.path(f"run/crosswalk/codes-{c}.json")) for c in cfg["roles"]["crosswalk_coders"]}
    preds = list(seal.predictions(ws.path("sealed/self-prediction.md").read_text(encoding="utf-8")))
    supported = {cid for cid, eras in agree["construct_status"].items() if "supported" in eras.values()}
    inductive_ok = agree["inductive"]["verdict"] in REPORTABLE
    eligible = supported if inductive_ok else set()
    instrument = ipip.load_instrument()
    self_report = ipip.score(ipip.parse_responses(ws.path("sealed/ipip-120.csv").read_text(encoding="utf-8"),
                                                  instrument), instrument)
    observer = deductive_domains(agree["deductive_collapsed"], instrument)
    return {
        "corpus": store.read_json(ws.path("prepare/stats.json")),
        "fingerprints": {lin: {k: v for k, v in q.items() if k != "evidence"}
                         for lin, q in qualify.qualified(ws).items()},
        "agreement": {k: agree[k] for k in ("inductive", "deductive", "downgrades")}
        | {"integrity_audit": agree.get("integrity_audit")},
        "constructs": [{"id": c["id"], "name": c["name"], "definition": c["definition"], "lineages": c["lineages"],
                        "status": agree["construct_status"][c["id"]]} for c in book["constructs"]],
        "predictions": prediction_rates(codes, preds, eligible) | {"inductive_reportable": inductive_ok},
        "deductive_vs_ipip": domain_comparison(observer, self_report)
        | {"deductive_reportable": agree["deductive"]["verdict"] in REPORTABLE},
        "observer_facets": observer["facets"],
    }
