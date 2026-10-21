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
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from abx import agreement, calibration, config, extract, invoke, ipip, prompts, report, seal, store, unmask
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


class _Judged(NamedTuple):
    era: str | None
    label: str | None


def _calibration(ws: store.Workspace) -> tuple[dict, list[str]]:
    """The calibration rebuilt from evidence: each recorded part's labels from both judges' frozen call records, each
    target's zoner label from the frozen zoning. Returns the summary and every way `calibration.json` departs from
    it: a part or target outside its era, a judge labelling a sentence twice or not at all, a repeated target, or a
    stored label that differs from its record."""
    rec = store.read_json(ws.path(calibration.PATH))
    eras = store.read_json(ws.path("prepare/eras.json"))["eras"]
    zoning = {e["id"]: store.read_json(ws.path(f"prepare/zoning/{e['id']}.json")) for e in eras}
    roster = sorted(config.load(ws).lineages)  # one judge per configured lineage, whatever the record claims
    out = [] if sorted(rec["judges"]) == roster else [f"calibration: judges {rec['judges']} are not {roster}"]
    judged = {lin: {} for lin in roster}
    for part in rec["parts"]:
        if not set(part["sentence_ids"]) <= set(zoning[part["era"]]):
            out.append(f"calibration: {part['era']} part {part['part']} holds sentences from another era")
        for lin in roster:
            path = ws.path(f"run/calls/prepare/calibration_judge/{lin}-r0-{part['era']}.{part['part']}.json")
            rows = store.read_json(path)["output"]["labels"]
            ids = [lab["sentence_id"] for lab in rows]
            if len(ids) != len(set(ids)) or sorted(ids) != sorted(part["sentence_ids"]):
                out.append(f"calibration: {lin}'s labels for {part['era']} part {part['part']} do not cover its "
                           "sentences exactly once")
            judged[lin] |= {lab["sentence_id"]: _Judged(part["era"], lab["label"]) for lab in rows}
    ids = [t["sentence_id"] for t in rec["targets"]]
    if len(ids) != len(set(ids)):
        out.append("calibration: a target is repeated")
    counts = {"fk": 0, "kept": 0, "fr": 0, "removed": 0, "same": 0, "same_side": 0, "kept_all": 0, "removed_all": 0}
    for t in {t["sentence_id"]: t for t in rec["targets"]}.values():
        sid, era = t["sentence_id"], t["era"]
        labels = {lin: judged[lin].get(sid, _Judged(None, None)) for lin in roster}
        if sid not in zoning[era] or t["zoner"] != zoning[era][sid] or sorted(t["judges"]) != roster or \
                any(labels[lin] != _Judged(era, t["judges"][lin]) for lin in roster):
            out.append(f"calibration: target {sid} does not match its zoning and judge records")
            continue
        votes = [j.label for j in labels.values()]
        sides = {"keep" if v == "keep" else "removed" for v in votes}
        counts["same"] += len(set(votes)) == 1
        counts["same_side"] += len(sides) == 1
        stratum = "kept" if zoning[era][sid] == "keep" else "removed"
        counts[f"{stratum}_all"] += 1
        if len(sides) > 1:
            continue  # disputed: in neither rate
        counts[stratum] += 1
        if stratum == "kept":
            counts["fk"] += sides == {"removed"}
        else:
            counts["fr"] += sides == {"keep"}
    n = counts["kept_all"] + counts["removed_all"]
    fk = {"count": counts["fk"], "of": counts["kept"],
          "rate": counts["fk"] / counts["kept"] if counts["kept"] else None}
    fr = {"count": counts["fr"], "of": counts["removed"],
          "rate": counts["fr"] / counts["removed"] if counts["removed"] else None}
    if n < 100:
        reason = "too_small"
    elif fk["rate"] is None or fr["rate"] is None:
        reason = "undefined"
    elif fk["rate"] > .05 or fr["rate"] > .2:
        reason = "over_limit"
    else:
        reason = None
    return {"limits": {"false_keep": .05, "false_remove": .2}, "held_out": n, "false_keep": fk, "false_remove": fr,
            "disputed": {"keep": counts["kept_all"] - counts["kept"],
                         "removed": counts["removed_all"] - counts["removed"]},
            "judge_agreement": {"three_label": counts["same"] / n if n else None,
                                "collapsed": counts["same_side"] / n if n else None, "of": n},
            "judges": roster, "passed": reason is None, "reason": reason}, out


# The stages whose call records exist when `extract` runs its integrity audit.
AUDITED = ("prepare", "freeze", "extract")


def _audit(ws: store.Workspace, eras: list[str]) -> dict:
    """The integrity audit as it must have run inside `extract`, before generation C: over the prepare, freeze and
    extract call records, with generations A and B frozen, against the frozen qualification baseline."""
    records = [p for stage in AUDITED for p in sorted(ws.root.glob(f"run/calls/{stage}/**/*.json"))]
    bad_events = outside = 0
    for path in records:
        rec = store.read_json(path)
        evs = invoke.decode_events(rec.get("events"))
        if evs is None or invoke.outcome(rec["lineage"], rec.get("exit"), evs) != "success":
            bad_events += 1
        rater = (rec["lineage"], rec["run"]) if rec["run"] is not None else None
        try:
            prompts.check_allowlist(rec["role"], list(rec["input_artifacts"]), rater=rater, era=rec["era"],
                                    era_order=eras)
        except AbxError:
            outside += 1
    incidents = sum(1 for stage in AUDITED for p in ws.root.glob(f"run/incidents/{stage}/**/*.json")
                    if store.read_json(p)["kind"] == "tool_event")
    fresh = store.read_json(ws.path(extract.REQUALIFICATION_AUDIT))
    baseline = store.read_json(ws.path(invoke.QUALIFICATION_A))
    moved = sum(1 for lin, q in fresh.items() if any(q.get(k) != baseline[lin].get(k) for k in invoke.FINGERPRINT_KEYS))
    clean = not bad_events and not incidents
    return {
        "requalify": {"ok": not moved, "code": "fingerprint_moved" if moved else "requalified",
                      "counts": {"lineages_moved": moved}},
        "events": {"ok": clean, "code": "clean" if clean else "tool_events",
                   "counts": {"records": len(records), "records_with_tool_events": bad_events,
                              "tool_event_incidents": incidents}},
        "allowlist": {"ok": not outside, "code": "within_allowlists" if not outside else "outside_allowlist",
                      "counts": {"records": len(records), "outside": outside}},
        "manifest": {"ok": True, "code": "verified", "counts": {"generations": 2}},
    }


def _arm(arm: agreement.ArmResult) -> dict:
    return {"metric": arm.metric, "alpha": arm.alpha, "verdict": arm.verdict, "reason": arm.reason,
            "paired_fraction": arm.paired_fraction, "raw_agreement": arm.raw_agreement,
            "missing_rate": arm.missing_rate, "stability": dict(sorted(arm.stability.items())),
            "units": len(arm.units), "integrity_audit_due": arm.integrity_audit_due}


def _invalid_outputs(ws: store.Workspace) -> dict[str, int]:
    """Counted from the incidents generations C and D froze, never from whatever the folder holds now."""
    manifest = [json.loads(line) for line in ws.path(store.MANIFEST).read_text().splitlines() if line.strip()]
    frozen = {e["gen"]: [rel for rel in e["artifacts"] if rel.startswith("run/incidents/")] for e in manifest}
    stages = {"prepare": frozen.get("C", []), "freeze": frozen.get("C", []), "extract": frozen.get("C", []),
              "unmask": frozen.get("D", [])}
    return {stage: sum(1 for rel in rels if rel.startswith(f"run/incidents/{stage}/")
                       and json.loads(ws.path(rel).read_text())["kind"] == "invalid_output")
            for stage, rels in stages.items()}


def _foils(ws: store.Workspace, eras: list[str], ratings: extract.Ratings, lineages: list[str]) -> dict:
    """Kept foils re-derived from the authored foils and each era's audit, then their endorsement counted."""
    authored = {e: store.read_json(ws.path(f"prereg/foils/{e}.json"))["foils"] for e in eras}
    audits = {e: store.read_json(ws.path(f"run/audit/{e}.json")) for e in eras}
    drops = {e: {d["foil_id"]: d["reason"] for d in audits[e]["foils"] if d["decision"] == "drop"} for e in eras}
    kept = [{**f, "era": e} for e in eras for f in authored[e] if f["id"] not in drops[e]]
    endorsement = {}
    for kind in ("clear", "near_miss", "anchored"):
        mine = [f for f in kept if f["type"] == kind]
        by = {}
        for lin in lineages:
            got = [v["verdict"] for key, rows in ratings.verdicts.items() if key.lineage == lin
                   for f in mine if key.era == f["era"] for v in rows if v["item_id"] == f["item_id"]]
            present = got.count("present")
            by[lin] = {"verdicts": len(got), "present": present, "rate": present / len(got) if got else None}
        endorsement[kind] = {"items": len(mine), "by_lineage": by}
    flags: dict[str, list[str]] = {}
    for e in eras:
        for f in audits[e]["flags"]:
            flags.setdefault(f["construct_id"], []).append(e)
    return {"kept": kept, "foils": {"authored": sum(map(len, authored.values())),
                                    "dropped": [{"era": e, "id": i, "reason": r} for e in eras
                                                for i, r in sorted(drops[e].items())],
                                    "endorsement": endorsement},
            "audit_flags": dict(sorted(flags.items()))}


def _with_foils(ratings: extract.Ratings, book: dict, kept: list[dict], eras: list[str]) -> agreement.ArmResult:
    """The diagnostic arm rebuilt here: binary values, construct and kept-foil units in every era."""
    runs: dict = {}
    for key, rows in ratings.verdicts.items():
        cell = runs.setdefault(key.lineage, {}).setdefault(key.run, {})
        for v in rows:
            cell[(v["item_id"], key.era)] = "present" if v["verdict"] == "present" else "not_present"
    units = [(item["item_id"], era) for item in [*book["constructs"], *kept] for era in eras]
    return agreement.arm(runs, units, "nominal")


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
    audit = _audit(ws, eras) if inductive.integrity_audit_due or deductive_arm.integrity_audit_due else None
    invalid = _invalid_outputs(ws)
    foiled = _foils(ws, eras, ratings, lineages)
    calibrated, _ = _calibration(ws)
    diag = _with_foils(ratings, book, foiled["kept"], eras)
    return {
        "corpus": _corpus(ws),
        "calibration": calibrated,
        "fingerprints": {lin: {k: v for k, v in q.items() if k != "evidence"}
                         for lin, q in store.read_json(ws.path(invoke.QUALIFICATION_A)).items()},
        "agreement": {"inductive": _arm(inductive), "deductive": _arm(deductive_arm),
                      "downgrades": sum(1 for rows in ratings.verdicts.values() for v in rows if v["downgrade"]),
                      "integrity_audit": audit,
                      "inductive_with_foils": {"metric": diag.metric, "alpha": diag.alpha, "units": len(diag.units),
                                               "paired_fraction": diag.paired_fraction,
                                               "raw_agreement": diag.raw_agreement, "missing_rate": diag.missing_rate}},
        "foils": foiled["foils"],
        "audit_flags": foiled["audit_flags"],
        "constructs": [{"id": c["id"], "name": c["name"], "definition": c["definition"], "lineages": c["lineages"],
                        "status": status[c["id"]]} for c in book["constructs"]],
        "predictions": unmask.prediction_rates(codes, preds, supported if inductive_ok else set())
        | {"inductive_reportable": inductive_ok},
        "deductive_vs_ipip": unmask.domain_comparison(unmask.deductive_domains(collapsed, instrument), self_report)
        | {"deductive_reportable": deductive_arm.verdict in unmask.REPORTABLE},
        "domain_names": instrument["domains"],
        "invalid_outputs": {"by_stage": invalid, "total": sum(invalid.values()), "max_attempts": 3},
    }


def _diff(got, want, path="") -> list[str]:
    if isinstance(want, dict) and isinstance(got, dict):
        out = [f"{path}.{k}: missing" for k in want if k not in got]
        out += [f"{path}.{k}: unexpected" for k in got if k not in want]
        return out + [d for k in want if k in got for d in _diff(got[k], want[k], f"{path}.{k}")]
    if isinstance(want, list) and isinstance(got, list) and len(got) == len(want):
        return [d for i, (g, w) in enumerate(zip(got, want, strict=True)) for d in _diff(g, w, f"{path}[{i}]")]
    return [] if got == want else [f"{path}: reported {got!r}, recomputed {want!r}"]


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def _num(v, digits=3) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}"


def _rows(want: dict) -> list[str]:
    """The lines report.md must contain, written here from the rebuilt values without the production renderer."""
    rows = []
    for era, st in want["corpus"].items():
        rows.append(f"- Era {era}: {st['sentences']} sentences in {st['segments']} segments; zoning kept "
                    f"{_pct(st['kept_ratio'])} of {st['words']} words ({st['band']}); {st['mixed']} mixed and "
                    f"{st['removed']} reflective sentences removed.")
    for label, key in (("Inductive constructs", "inductive"), ("Deductive facets (strict)", "deductive")):
        a = want["agreement"][key]
        rows.append(f"- **{label}** ({a['metric']}, {a['units']} units): α = {_num(a['alpha'])}, ")
        rows.append(f"  - Units with both lineages: {_pct(a['paired_fraction'])}; raw agreement on them: "
                    f"{_pct(a['raw_agreement'])}; missing: {_pct(a['missing_rate'])}; stability α within lineage: "
                    + ", ".join(f"{lin} {_num(v)}" for lin, v in sorted(a["stability"].items())) + ".")
    c = want["calibration"]
    rows.append(f"- Zoning calibration: {c['held_out']} held-out sentences labelled blind by "
                + " and ".join(c["judges"]) + f" judges; where both judges agree, false keeps "
                f"{c['false_keep']['count']} of {c['false_keep']['of']} ({_pct(c['false_keep']['rate'])}; limit 5%) "
                f"and false removals {c['false_remove']['count']} of {c['false_remove']['of']} "
                f"({_pct(c['false_remove']['rate'])}; limit 20%); the judges split on {c['disputed']['keep']} kept and "
                f"{c['disputed']['removed']} cut sentences, which are left out and unresolved; they gave the same "
                f"label to {_pct(c['judge_agreement']['three_label'])} and agreed on keep or remove for "
                f"{_pct(c['judge_agreement']['collapsed'])}.")
    rows.append(f"rules: {want['agreement']['downgrades']}.")
    n = want["invalid_outputs"]["by_stage"]
    rows.append(f"up to 3 attempts): {sum(n.values())} (prepare {n['prepare']}, freeze {n['freeze']}, "
                f"extract {n['extract']}, unmask {n['unmask']}).")
    audit = want["agreement"]["integrity_audit"]
    if audit:
        ev, al = audit["events"]["counts"], audit["allowlist"]["counts"]
        rows.append(f"events: {ev['records']} call records audited, none with a tool event" if audit["events"]["ok"]
                    else f"events: {ev['records_with_tool_events']} call record(s)")
        rows.append(f"allowlist: {al['records']} call records within their roles' allowlists"
                    if audit["allowlist"]["ok"] else f"allowlist: {al['outside']} of {al['records']} call records")
        generations = audit["manifest"]["counts"]["generations"]
        rows.append(f"manifest: manifest chain verified across {generations} generations")
    d = want["agreement"]["inductive_with_foils"]
    rows.append(f"- Constructs plus foils (diagnostic, not a gate; {d['units']} units): α = {_num(d['alpha'])}; units "
                f"with both lineages: {_pct(d['paired_fraction'])}; raw agreement on them: {_pct(d['raw_agreement'])}.")
    f = want["foils"]
    rows.append(f"- Foils written: {f['authored']}; dropped by the audit as unclear: "
                + (", ".join(f"{d['era']} {d['id']}" for d in f["dropped"]) or "none") + ".")
    for kind, label, rate in (("clear", "Clear foils", "false-positive"), ("near_miss", "Near-miss foils",
                                                                          "false-positive"),
                              ("anchored", "Anchored foils", "recovery")):
        t = f["endorsement"][kind]
        rows.append(f"- {label} ({rate} rate, {t['items']} kept): " + "; ".join(
            f"{lin} {_pct(c['rate'])} ({c['present']} of {c['verdicts']} verdicts)"
            for lin, c in sorted(t["by_lineage"].items())) + ".")
    rows.append("the audit flagged with counter-evidence their definition does not account for: "
                + (", ".join(f"{cid} ({', '.join(e)})" for cid, e in want["audit_flags"].items()) or "none") + ".")
    eras = list(want["corpus"])
    for c in want["constructs"]:
        rows.append(f"| {c['id']} | {c['name']} | {', '.join(c['lineages'])} | "
                    + " | ".join(c["status"][e] for e in eras) + " |")
    p = want["predictions"]
    rows.append(f"- Predictions matched: {len(p['matched'])} of {p['predictions_decided']} decided "
                f"({_pct(p['predictions_matched_rate'])})")
    rows.append(f"- Supported constructs matched to a prediction: {len(p['constructs_matched'])} of "
                f"{p['supported_eligible']} ({_pct(p['supported_constructs_matched_rate'])}).")
    rows.append(f"- Coder agreement on prediction-construct pairs: {_pct(p['coder_agreement'])}.")
    d = want["deductive_vs_ipip"]
    for dom, row in d["domains"].items():
        same = "n/a" if row["same_band"] is None else ("yes" if row["same_band"] else "no")
        rows.append(f"| {want['domain_names'][dom]} | {_num(row['observer'], 2)} | {row['observer_band'] or 'n/a'} | "
                    f"{_num(row['ipip'], 2)} | {row['ipip_band'] or 'n/a'} | {same} |")
    rows.append(f"Same band in {_pct(d['agreement_rate'])} of {d['compared']} domains compared.")
    return rows


def compare(results: dict, report_md: str, want: dict) -> list[str]:
    """Field-by-field differences; rows report.md must show; then any line differing from the rebuilt report."""
    plain = json.loads(json.dumps(want))
    out = _diff(results, plain)
    out += [f"report.md lacks the row {row[:60]!r}…" for row in _rows(plain) if row not in report_md]
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
    out += _calibration(ws)[1]
    return out + compare(store.read_json(ws.path("report/results.json")), report_md, expected(ws))


if __name__ == "__main__":
    found = problems(store.Workspace(Path(sys.argv[1]).resolve()))
    print("\n".join(found) or "every report figure recomputes")
    sys.exit(1 if found else 0)
