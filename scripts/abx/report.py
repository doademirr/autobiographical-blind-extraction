"""`report.md` from `results.json`. Formatting only: every number arrives already computed."""

from .agreement import MIN_PAIRED, REPORT, TENTATIVE

__all__ = ["render"]

VERDICT_TEXT = {"report": f"reportable (α ≥ {REPORT:.2f})",
                "tentative": f"tentative ({TENTATIVE:.3f} ≤ α < {REPORT:.2f})", "not_reportable": "not reportable"}
REASON_TEXT = {"no_units": "there is nothing to rate (an empty codebook)",
               "no_pairable_unit": "no unit has values from both lineages",
               "no_variation": "the ratings do not vary, so agreement is undefined",
               "fewer_lineages": "fewer than two lineages rated",
               "low_pairing": f"fewer than {MIN_PAIRED:.0%} of units carry a value from both lineages"}


def num(value, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def pct(value) -> str:
    return "n/a" if value is None else f"{value:.0%}"


AUDIT_TEXT = {"requalified": "both lineages requalified with unchanged fingerprints",
              "fingerprint_moved": "a fingerprint moved since the frozen baseline",
              "clean": "{records} call records audited, none with a tool event",
              "tool_events": "{records_with_tool_events} call record(s) and {tool_event_incidents} incident(s) "
                             "with tool events",
              "within_allowlists": "{records} call records within their roles' allowlists",
              "outside_allowlist": "{outside} of {records} call records outside their role's allowlist",
              "verified": "manifest chain verified across {generations} generations"}


def _check_text(check: dict) -> str:
    template = AUDIT_TEXT.get(check["code"], "could not complete ({code})")
    return template.format(code=check["code"], **check["counts"])


def _arm(name: str, arm: dict) -> list[str]:
    stab = ", ".join(f"{lin} {num(v)}" for lin, v in sorted(arm["stability"].items()))
    lines = [f"- **{name}** ({arm['metric']}, {arm['units']} units): α = {num(arm['alpha'])}, "
             f"{VERDICT_TEXT[arm['verdict']]}."]
    if arm["reason"]:
        lines.append(f"  - Undefined: {REASON_TEXT.get(arm['reason'], arm['reason'])}.")
    lines.append(f"  - Units with both lineages: {pct(arm['paired_fraction'])}; raw agreement on them: "
                 f"{pct(arm['raw_agreement'])}; missing: {pct(arm['missing_rate'])}; "
                 f"stability α within lineage: {stab}.")
    return lines


FOIL_TYPES = (("clear", "Clear foils", "false-positive rate"), ("near_miss", "Near-miss foils", "false-positive rate"),
              ("anchored", "Anchored foils", "recovery rate"))


def _foils(r: dict) -> list[str]:
    f = r["foils"]
    dropped = ", ".join(f"{d['era']} {d['id']}" for d in f["dropped"]) or "none"
    out = ["## Foils and the blind audit", "",
           "Foils are test items written from one era with an answer set in advance (absent for clear and near-miss "
           "foils, present for anchored ones), and mixed into the card so raters cannot tell them from constructs. "
           "The rates count every rater run's verdict in the foil's own era. They are descriptive: replicate runs are "
           "not independent samples, and the audit lineage chose which foils stayed, so they do not rank the "
           "lineages.", "",
           f"- Foils written: {f['authored']}; dropped by the audit as unclear: {len(f['dropped'])} ({dropped})."]
    for key, label, rate in FOIL_TYPES:
        t = f["endorsement"][key]
        cells = "; ".join(f"{lin} {pct(c['rate'])} ({c['present']} of {c['verdicts']} verdicts)"
                          for lin, c in sorted(t["by_lineage"].items()))
        out.append(f"- {label} ({rate}, {t['items']} kept): {cells}.")
    flagged = ", ".join(f"{cid} ({', '.join(eras)})" for cid, eras in r["audit_flags"].items()) or "none"
    out += [f"- Constructs the audit flagged with counter-evidence their definition does not account for: {flagged}. "
            "Flags are reported, not acted on; the construct table shows what raters found.", ""]
    return out


def render(r: dict) -> str:
    out = ["# Blind extraction report", "",
           "## This is not a clinical assessment", "",
           "This report describes patterns that two families of language models found, blind, in a written life "
           "record, "
           "and how they line up with your own predictions and questionnaire answers. It is not a diagnosis, a "
           "psychological evaluation or advice. The claim it supports is agreement between raters, never objectivity. "
           "If anything in it is distressing, set it down and talk to someone you trust.", "",
           "## How it was made", ""]
    for era, s in r["corpus"].items():
        out.append(f"- Era {era}: {s['sentences']} sentences in {s['segments']} segments; zoning kept "
                   f"{pct(s['kept_ratio'])} of {s['words']} words ({s['band']}); {s['mixed']} mixed and "
                   f"{s['removed']} reflective sentences removed.")
    for lin, fp in sorted(r["fingerprints"].items()):
        out.append(f"- {lin}: {fp['cli_version']}, model {fp['resolved_model']}.")
    out += ["", "## Agreement (computed by script)", ""]
    out += _arm("Inductive constructs", r["agreement"]["inductive"])
    out += _arm("Deductive facets (strict)", r["agreement"]["deductive"])
    d = r["agreement"]["inductive_with_foils"]
    out.append(f"- Constructs plus foils (diagnostic, not a gate; {d['units']} units): α = {num(d['alpha'])}; units "
               f"with both lineages: {pct(d['paired_fraction'])}; raw agreement on them: {pct(d['raw_agreement'])}.")
    out.append(f"- Verdicts downgraded to insufficient by the recurrence and counter-evidence rules: "
               f"{r['agreement']['downgrades']}.")
    n = r["invalid_outputs"]
    out.append(f"- Invalid outputs (failed their schema or validator; each call gets up to {n['max_attempts']} "
               f"attempts): {n['total']} ({', '.join(f'{stage} {count}' for stage, count in n['by_stage'].items())}).")
    audit = r["agreement"]["integrity_audit"]
    if audit:
        verdict = "every check passed" if all(c["ok"] for c in audit.values()) else "a check failed"
        checks = "; ".join(f"{name}: {_check_text(check)}" for name, check in audit.items())
        out.append(f"- Very high agreement triggered the integrity audit: {verdict} ({checks}). High agreement is "
                   "reported with the caveat that both lineages share a method and may share training data.")
    eras = list(r["corpus"])
    out += ["", *_foils(r), "## Constructs", "", f"| Id | Construct | Found by | {' | '.join(eras)} |",
            "|---|---|---|" + "---|" * len(eras)]
    for c in r["constructs"]:
        out.append(f"| {c['id']} | {c['name']} | {', '.join(c['lineages'])} | "
                   + " | ".join(c["status"][e] for e in eras) + " |")
    out += ["", "Supported: both lineages find the construct in the era. Contested: they disagree. Not-shown: "
            "neither finds it. One-lineage: one side has no verdict; never counted as supported. No-verdict: neither "
            "lineage has one (tied or missing runs).", ""]
    p = r["predictions"]
    out += ["## Your predictions", ""]
    if not p["inductive_reportable"]:
        out.append("The inductive arm is not reportable, so no construct is eligible to match a prediction.")
    out += [f"- Predictions matched: {len(p['matched'])} of {p['predictions_decided']} decided "
            f"({pct(p['predictions_matched_rate'])}); ambiguous (coders disagree, excluded): "
            f"{', '.join(p['ambiguous']) or 'none'}.",
            f"- Supported constructs matched to a prediction: {len(p['constructs_matched'])} of "
            f"{p['supported_eligible']} ({pct(p['supported_constructs_matched_rate'])}).",
            f"- Coder agreement on prediction-construct pairs: {pct(p['coder_agreement'])}."]
    for pid, outcome in p["outcome"].items():
        out.append(f"  - {pid}: {outcome}")
    if p["descriptive_matches"]:
        out.append(f"- Descriptive only (matches to constructs that are not supported): "
                   f"{', '.join(m['prediction_id'] + '~' + m['construct_id'] for m in p['descriptive_matches'])}.")
    d = r["deductive_vs_ipip"]
    out += ["", "## Observer estimate vs your IPIP-NEO-120", "",
            "The observer estimate covers the whole record; your questionnaire describes you now. "
            "Both your predictions "
            "and the questionnaire are self-report, so this is not independent triangulation.", ""]
    if not d["deductive_reportable"]:
        out += ["The deductive arm is not reportable; the rows below are descriptive only.", ""]
    out += ["| Domain | Observer (1–7) | Band | IPIP (1–5) | Band | Same band |", "|---|---|---|---|---|---|"]
    for dom, row in d["domains"].items():
        same = "n/a" if row["same_band"] is None else ("yes" if row["same_band"] else "no")
        out.append(f"| {r['domain_names'][dom]} | {num(row['observer'], 2)} | {row['observer_band'] or 'n/a'} | "
                   f"{num(row['ipip'], 2)} | {row['ipip_band'] or 'n/a'} | {same} |")
    out += ["", f"Same band in {pct(d['agreement_rate'])} of {d['compared']} domains compared.", "",
            "## Limits", "",
            "- Raters saw one era at a time, so patterns that only show across eras are not captured.",
            "- Discovery used a fixed panel; saturation was not established.",
            "- Narrative over-reads emotionally charged scenes and misses traits that show as absence.",
            "- Models may already know a published text; on one, this run tests the method's plumbing, "
            "not its validity.",
            ""]
    return "\n".join(out)
