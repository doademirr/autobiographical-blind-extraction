"""`extract`: the blind engine, from discovery to the agreement gates (generations B and C).

Discovery (lineage x run x era, future-blind) -> pooled candidates -> clean-room codebook
author + validator -> card (generation B) -> recode -> deductive ledgers and strict
scoring -> agreement by script -> integrity audit when agreement is very high
(generation C). Every model call goes through `invoke.call`.
"""

import hashlib
import re

from . import agreement, artifacts, invoke, prepare, prompts, qualify, seal, store
from .errors import CallFailed, IntegrityError, IsolationError, UsageError

COMPOUND_NAME = re.compile(r"/|&|\+|,|;|\band\b|\bor\b|\bvs\.?\b|\bthen\b|\bfollowed by\b", re.I)
MAX_CONSTRUCTS = 80
FACETS = [f"{d}{i}" for d in "NEOAC" for i in range(1, 7)]


class Run:
    """Everything one `extract` invocation shares: workspace, config, eras, sentences, secrets."""

    def __init__(self, ws: store.Workspace):
        self.ws = ws
        self.cfg = store.read_json(ws.path("config.json"))
        self.qual = qualify.qualified(ws)
        self.eras = store.read_json(ws.path("prepare/eras.json"))["eras"]
        self.era_ids = [e["id"] for e in self.eras]
        self.sentences = {s["id"]: s for s in store.read_json(ws.path("prepare/sentences.json"))}
        self.seg_index = {s["id"]: i for i, s in enumerate(store.read_json(ws.path("prepare/segments.json")))}
        self.kept = {e: {sid for sid, lab in store.read_json(ws.path(f"prepare/zoning/{e}.json")).items()
                         if lab == "keep"} for e in self.era_ids}
        self.secrets = prepare.load_secrets(ws)
        self.resolve = artifacts.resolver(ws)
        self.lineages = list(self.cfg["lineages"])
        self.runs = range(1, self.cfg["runs"] + 1)

    def call(self, role, schema, slots, lineage, run, era, generation, params=None, validate=None):
        rater = (lineage, run) if run is not None else None
        prompt = prompts.assemble(role, {**slots, "schema": f"schema:{schema}"}, self.resolve, params or {},
                                  rater=rater, era=era, era_order=self.era_ids)
        prompts.audit(prompt, self.secrets)
        spec = invoke.CallSpec(stage="extract", role=role, lineage=lineage, run=run, era=era, generation=generation,
                               schema_name=schema, prompt=prompt, validate=validate)
        return invoke.call(self.ws, self.cfg, spec, self.qual[lineage])

    def label(self, era: str) -> str:
        e = next(x for x in self.eras if x["id"] == era)
        return e["label"] or e["id"]

    def cites_kept(self, era: str):
        def check(ids) -> list[str]:
            bad = [i for i in ids if i not in self.kept[era]]
            return [f"cites sentence ids outside the zoned era: {bad[:5]}"] if bad else []
        return check


def _all_ids(out: dict, *paths) -> list[str]:
    """Sentence ids cited anywhere under the given nested keys."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in paths and isinstance(v, list) and all(isinstance(x, str) for x in v):
                    found.extend(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(out)
    return found


# --- discovery ---------------------------------------------------------------------------------------------------

def discovery(r: Run) -> None:
    for lineage in r.lineages:
        for run in r.runs:
            hypotheses: list[str] = []
            for k, era in enumerate(r.era_ids):
                slots = {"era": f"era:{era}"}
                params = {"era_label": r.label(era)}
                if k == 0:
                    params["hypotheses"] = "(none: this is the first era)"
                else:
                    slots["hypotheses"] = f"hypotheses:{lineage}:{run}:{r.era_ids[k - 1]}"
                check = r.cites_kept(era)
                out = r.call("discovery", "discovery", slots, lineage, run, era, "B", params,
                             validate=lambda o, check=check: check(_all_ids(o, "sentence_ids")))
                store.write_json(artifacts.path_of(r.ws, f"discovery:{lineage}:{run}:{era}"), out)
                hypotheses += out["hypotheses"]
                store.write_text_atomic(artifacts.path_of(r.ws, f"hypotheses:{lineage}:{run}:{era}"),
                                        "".join(f"- {h}\n" for h in hypotheses) or "- (none)\n")


def pool(r: Run) -> dict[str, dict]:
    """Every discovery candidate under an opaque ref; the map back to its rater stays local."""
    candidates = {}
    for lineage in r.lineages:
        for run in r.runs:
            for era in r.era_ids:
                out = store.read_json(artifacts.path_of(r.ws, f"discovery:{lineage}:{run}:{era}"))
                for t in out["traits"]:
                    ref = f"c{len(candidates) + 1:03d}"
                    candidates[ref] = {"lineage": lineage, "run": run, "era": era, "trait": t["trait"],
                                       "alexander_id": t["alexander_id"]}
    store.write_json(r.ws.path("run/discovery/pool.json"), candidates)
    store.write_text_atomic(artifacts.path_of(r.ws, "pool:all"), "".join(
        f"{ref} | {c['trait']} | {c['alexander_id']}\n" for ref, c in candidates.items()))
    return candidates


# --- codebook ----------------------------------------------------------------------------------------------------

def validate_codebook(out: dict, refs: set[str]) -> list[str]:
    """Atomic names, rules present, unique ids, and every candidate placed exactly once."""
    problems = []
    cons = out["constructs"]
    ids = [c["id"] for c in cons]
    if len(ids) != len(set(ids)):
        problems.append("duplicate construct ids")
    if len(cons) > MAX_CONSTRUCTS:
        problems.append(f"more than {MAX_CONSTRUCTS} constructs")
    problems += [f"{c['id']} name is not atomic: {c['name']!r}" for c in cons if COMPOUND_NAME.search(c["name"])]
    traces: dict[str, int] = {}
    for c in cons:
        for ref in c["trace"]:
            traces[ref] = traces.get(ref, 0) + 1
    appendix: dict[str, str] = {}
    for a in out["appendix"]:
        if a["candidate_ref"] in appendix:
            problems.append(f"{a['candidate_ref']} appears twice in the appendix")
        appendix[a["candidate_ref"]] = a["disposition"]
    unknown = (set(traces) | set(appendix)) - refs
    if unknown:
        problems.append(f"unknown candidate refs {sorted(unknown)[:5]}")
    for ref in sorted(refs):
        n, disp = traces.get(ref, 0), appendix.get(ref)
        ok = (disp is None and n == 1) or (disp == "excluded" and n == 0) or (disp == "merged" and n == 1) \
            or (disp == "split" and n >= 2)
        if not ok:
            problems.append(f"{ref} is not placed exactly once (traces {n}, appendix {disp})")
    return problems


def item_id(construct_id: str, salt: str) -> str:
    return "K" + hashlib.sha256(f"{construct_id}|{salt}".encode()).hexdigest()[:6]


def codebook(r: Run, candidates: dict[str, dict]) -> dict:
    lineage = r.cfg["roles"]["codebook_author"]
    out = r.call("codebook_author", "codebook", {"pool": "pool:all"}, lineage, None, None, "B",
                 validate=lambda o: validate_codebook(o, set(candidates)))
    salt = store.sha256_file(r.ws.path("prepare/redacted.txt"))
    constructs = []
    for c in out["constructs"]:
        lineages = sorted({candidates[ref]["lineage"] for ref in c["trace"]})
        constructs.append({**c, "lineages": lineages, "item_id": item_id(c["id"], salt)})
    if len({c["item_id"] for c in constructs}) != len(constructs):
        raise CallFailed("card item ids collide; rename a construct id and rerun")
    book = {"constructs": constructs, "appendix": out["appendix"]}
    store.write_json(r.ws.path("run/codebook/codebook.json"), book)
    card = sorted(constructs, key=lambda c: c["item_id"])
    store.write_text_atomic(artifacts.path_of(r.ws, "card:B"), "".join(
        f"- {c['item_id']}: {c['name']}. {c['definition']} Present when: {c['sufficiency_rule']}\n" for c in card))
    return book


# --- recode ------------------------------------------------------------------------------------------------------

def apply_bar(v: dict, seg_of) -> tuple[str, str | None]:
    """The script's verdict: present needs two occurrences in distinct, non-adjacent segments; absent a counter."""
    if v["verdict"] == "present":
        segs = [{seg_of(s) for s in occ["sentence_ids"]} for occ in v["occurrences"]]
        separate = any(all(abs(a - b) >= 2 for a in x for b in y)
                       for i, x in enumerate(segs) for y in segs[i + 1:])
        return ("present", None) if separate else ("insufficient", "present without two separate episodes")
    if v["verdict"] == "absent":
        return ("absent", None) if v["counter_sentence_ids"] else ("insufficient", "absent without a counter-sentence")
    return "insufficient", None


def recode(r: Run, book: dict) -> dict:
    items = {c["item_id"] for c in book["constructs"]}

    def seg_of(sid):
        return r.seg_index[r.sentences[sid]["segment_id"]]

    results = {}
    for lineage in r.lineages:
        for run in r.runs:
            for era in r.era_ids:
                check = r.cites_kept(era)

                def validate(o, check=check):
                    got = [v["item_id"] for v in o["verdicts"]]
                    if len(got) != len(set(got)) or set(got) != items:
                        return ["verdicts must cover every card item exactly once"]
                    return check(_all_ids(o, "sentence_ids", "counter_sentence_ids"))

                out = r.call("recode", "recode", {"card": "card:B", "era": f"era:{era}"}, lineage, run, era, "C",
                             {"era_label": r.label(era)}, validate)
                scored = []
                for v in out["verdicts"]:
                    final, reason = apply_bar(v, seg_of)
                    scored.append({"item_id": v["item_id"], "rater_verdict": v["verdict"], "verdict": final,
                                   "downgrade": reason})
                results[f"{lineage}|{run}|{era}"] = scored
                store.write_json(r.ws.path(f"run/recode/{lineage}-r{run}-{era}.json"), scored)
    return results


# --- deductive ---------------------------------------------------------------------------------------------------

def deductive(r: Run) -> dict:
    scores = {}
    for lineage in r.lineages:
        for run in r.runs:
            ledgers = []
            for era in r.era_ids:
                check = r.cites_kept(era)

                def validate(o, check=check):
                    if sorted(f["facet"] for f in o["facets"]) != sorted(FACETS):
                        return ["the ledger must list all 30 facets once"]
                    return check(_all_ids(o, "sentence_ids"))

                out = r.call("deductive_ledger", "ledger", {"era": f"era:{era}"}, lineage, run, era, "C",
                             {"era_label": r.label(era)}, validate)
                store.write_json(artifacts.path_of(r.ws, f"ledger:{lineage}:{run}:{era}"), out)
                ledgers.append({"era": r.label(era), **out})
            store.write_json(artifacts.path_of(r.ws, f"ledger:{lineage}:{run}:all"), ledgers)

            def validate_scores(o):
                return [] if sorted(s["facet"] for s in o["scores"]) == sorted(FACETS) \
                    else ["scores must cover all 30 facets once"]

            out = r.call("deductive_scorer", "scores", {"ledgers": f"ledger:{lineage}:{run}:all"}, lineage, run, None,
                         "C", validate=validate_scores)
            scores[f"{lineage}|{run}"] = {s["facet"]: s["score"] for s in out["scores"]}
            store.write_json(r.ws.path(f"run/deductive/scores-{lineage}-r{run}.json"), out)
    return scores


# --- agreement ---------------------------------------------------------------------------------------------------

def _arm_json(arm: agreement.ArmResult) -> dict:
    return {"metric": arm.metric, "alpha": arm.alpha, "verdict": arm.verdict, "reason": arm.reason,
            "paired_fraction": arm.paired_fraction, "raw_agreement": arm.raw_agreement,
            "missing_rate": arm.missing_rate, "stability": arm.stability, "units": len(arm.units),
            "integrity_audit_due": arm.integrity_audit_due}


def agree(r: Run, book: dict, verdicts: dict, scores: dict) -> dict:
    items = [c["item_id"] for c in book["constructs"]]
    units = [f"{i}@{e}" for i in items for e in r.era_ids]
    runs: dict = {lin: {str(run): {} for run in r.runs} for lin in r.lineages}
    for key, rows in verdicts.items():
        lineage, run, era = key.split("|")
        for v in rows:
            runs[lineage][run][f"{v['item_id']}@{era}"] = None if v["verdict"] == "insufficient" else v["verdict"]
    inductive = agreement.arm(runs, units, "nominal")
    druns: dict = {lin: {str(run): scores[f"{lin}|{run}"] for run in r.runs} for lin in r.lineages}
    deductive_arm = agreement.arm(druns, FACETS, "ordinal")
    statuses = {}
    for c in book["constructs"]:
        statuses[c["id"]] = {e: agreement.status([inductive.collapsed[lin][f"{c['item_id']}@{e}"]
                                                  for lin in r.lineages]) for e in r.era_ids}
    result = {
        "inductive": _arm_json(inductive), "deductive": _arm_json(deductive_arm),
        "construct_status": statuses,
        "inductive_collapsed": inductive.collapsed, "deductive_collapsed": deductive_arm.collapsed,
        "downgrades": sum(1 for rows in verdicts.values() for v in rows if v["downgrade"]),
    }
    if inductive.integrity_audit_due or deductive_arm.integrity_audit_due:
        result["integrity_audit"] = integrity_audit(r)
        if not all(c["ok"] for c in result["integrity_audit"].values()):
            store.write_json(r.ws.path("run/agreement.json"), result)
            raise IntegrityError("integrity audit failed after very high agreement; results invalidated")
    store.write_json(r.ws.path("run/agreement.json"), result)
    return result


def integrity_audit(r: Run) -> dict:
    def requalify():
        qualify.qualify(r.ws, r.cfg)
        return True, "both lineages requalified"

    def events():
        hits = [p for p in sorted(r.ws.root.glob("run/incidents/**/*.json"))
                if store.read_json(p)["kind"] == "tool_event"]
        return not hits, f"{len(hits)} tool-event incidents on record"

    def allowlists():
        for path in sorted(r.ws.root.glob("run/calls/**/*.json")):
            rec = store.read_json(path)
            rater = (rec["lineage"], rec["run"]) if rec["run"] is not None else None
            try:
                prompts.check_allowlist(rec["role"], list(rec["input_artifacts"]), rater=rater, era=rec["era"],
                                        era_order=r.era_ids)
            except (IsolationError, UsageError) as exc:
                return False, f"{r.ws.rel(path)}: {exc}"
        return True, "every call record within its role's allowlist"

    def manifest():
        store.verify_manifest(r.ws)
        return True, "manifest chain verified"

    return agreement.integrity_audit({"requalify": requalify, "events": events, "allowlist": allowlists,
                                      "manifest": manifest})


def extract(ws: store.Workspace) -> dict:
    store.verify_manifest(ws)
    seal.verify_sealed(ws)
    if "A" not in store.frozen_generations(ws):
        raise IntegrityError("generation A is not frozen; run `freeze` first")
    r = Run(ws)
    if "B" not in store.frozen_generations(ws):
        discovery(r)
        candidates = pool(r)
        codebook(r, candidates)
        store.append_generation(ws, "B", [
            "run/discovery/pool.json", "run/discovery/pool.md", "run/codebook/codebook.json", "run/codebook/card.md",
            *(ws.rel(p) for p in sorted(ws.root.glob("run/discovery/*-r*-*.json")))])
    book = store.read_json(ws.path("run/codebook/codebook.json"))
    if "C" in store.frozen_generations(ws):
        return store.read_json(ws.path("run/agreement.json"))
    verdicts = recode(r, book)
    scores = deductive(r)
    result = agree(r, book, verdicts, scores)
    outputs = [ws.rel(p) for g in ("run/recode/*.json", "run/deductive/*.json") for p in sorted(ws.root.glob(g))]
    store.append_generation(ws, "C", ["run/agreement.json", *outputs])
    return result

