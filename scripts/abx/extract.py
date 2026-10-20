"""`extract`: the blind engine, from discovery to the agreement gates (generations B and C).

Discovery (lineage x run x era, future-blind) -> pooled candidates -> clean-room codebook
author + validator -> card (generation B) -> recode -> deductive ledgers and strict
scoring -> agreement by script -> integrity audit when agreement is very high
(generation C). Every model call is a `CallRequest` through `invoke.call`.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import NamedTuple

from . import agreement, artifacts, config, invoke, ipip, lifecycle, prompts, qualify, store
from .errors import AbxError, IntegrityError

__all__ = ["MAX_CONSTRUCTS",
    "REQUALIFICATION_AUDIT",
    "STAGE",
    "RaterKey",
    "Ratings",
    "Unit",
    "apply_bar",
    "arms",
    "card_line",
    "estimate",
    "extract",
    "load_ratings",
    "validate_codebook",
]

# Markers that always join two claims. "and", "or" and commas are left to the author's instruction: in a live run
# they mostly joined two objects or near-synonyms of one trait, and a lexical gate on them failed good codebooks.
COMPOUND_NAME = re.compile(r"[/&+;]|\bvs\.?\b|\bthen\b|\bfollowed by\b", re.I)
MAX_CONSTRUCTS = 80
REQUALIFICATION_AUDIT = "run/requalification-audit.json"


class RaterKey(NamedTuple):
    lineage: str
    run: int
    era: str | None


class Unit(NamedTuple):
    """An inductive agreement unit: one card item in one era."""

    item_id: str
    era: str


@dataclass(frozen=True)
class Context:
    """What every step of one `extract` shares: the workspace, config, eras and sentence index."""

    ws: store.Workspace
    cfg: config.Config
    eras: tuple[Mapping, ...]
    sentences: Mapping[str, dict]
    seg_index: Mapping[str, int]
    kept: Mapping[str, frozenset[str]]
    facets: tuple[str, ...]

    @property
    def era_ids(self) -> list[str]:
        return [e["id"] for e in self.eras]

    @property
    def runs(self) -> range:
        return range(1, self.cfg.runs + 1)

    def where(self, sentence_id: str, era: str) -> str:
        """Where a sentence cited from `era` but outside its zoned text lies: zoned out of that same era
        (`removed:<era>`), in another era (`era:<id>`), or nowhere (`unknown`)."""
        s = self.sentences.get(sentence_id)
        home = next((e["id"] for e in self.eras if s and s["segment_id"] in e["segment_ids"]), None)
        return "unknown" if home is None else f"removed:{home}" if home == era else f"era:{home}"



def _context(ws: store.Workspace) -> Context:
    eras = tuple(store.read_json(ws.path("prepare/eras.json"))["eras"])
    kept = {e["id"]: frozenset(sid for sid, lab in store.read_json(ws.path(f"prepare/zoning/{e['id']}.json")).items()
                               if lab == "keep") for e in eras}
    return Context(ws=ws, cfg=config.load(ws), eras=tuple(MappingProxyType(e) for e in eras),
                   sentences=MappingProxyType({s["id"]: s for s in store.read_json(ws.path("prepare/sentences.json"))}),
                   seg_index=MappingProxyType({s["id"]: i for i, s in
                                               enumerate(store.read_json(ws.path("prepare/segments.json")))}),
                   kept=MappingProxyType(kept), facets=tuple(ipip.load_instrument(ws)["facets"]))


def _cited(node, keys: tuple[str, ...]) -> list[str]:
    """Sentence ids cited anywhere under the given keys."""
    if isinstance(node, dict):
        return [x for k, v in node.items() for x in (v if k in keys and isinstance(v, list) else _cited(v, keys))]
    if isinstance(node, list):
        return [x for v in node for x in _cited(v, keys)]
    return []


# The most ids one validation message names; the count is always complete.
MAX_NAMED = 20


def _outside(c: Context, era: str, ids: list[str]) -> list[str]:
    bad = [i for i in ids if i not in c.kept[era]]
    if not bad:
        return []
    named = ", ".join(f"{i} ({c.where(i, era)})" for i in bad[:MAX_NAMED])
    return [f"cites {len(bad)} sentence id(s) outside the zoned era: {named}"]


def _coverage(items: set[str], got: list[str]) -> list[str]:
    """Each card item exactly once, naming what is missing, repeated or not on the card."""
    missing = sorted(items - set(got))
    repeated = sorted({i for i in got if got.count(i) > 1})
    unknown = sorted(set(got) - items)
    if not (missing or repeated or unknown):
        return []
    parts = [f"{label} {', '.join(ids[:MAX_NAMED])}" for label, ids in
             (("missing", missing), ("repeated", repeated), ("not on the card", unknown)) if ids]
    return [f"verdicts must cover every card item exactly once: {'; '.join(parts)}"]


def estimate(ws: store.Workspace) -> lifecycle.Preflight:
    cfg = config.load(ws)
    eras = len(store.read_json(ws.path("prepare/eras.json"))["eras"])
    return lifecycle.Preflight(len(cfg.lineages) * cfg.runs * (3 * eras + 1) + 1, 2,
                               "discovery, recode and ledger per rater and era, one scorer per rater, one codebook "
                               "author; if agreement is very high, one leak probe per lineage for the integrity audit")


# --- discovery ---------------------------------------------------------------------------------------------------

def _discovery(c: Context) -> None:
    for lineage in c.cfg.lineages:
        for run in c.runs:
            hypotheses: list[str] = []
            for k, era in enumerate(c.era_ids):
                slots = {"era": f"era:{era}"}
                if k > 0:
                    slots["hypotheses"] = f"hypotheses:{lineage}:{run}:{c.era_ids[k - 1]}"
                out = invoke.call(c.ws, c.cfg, invoke.CallRequest(
                    stage="extract", role="discovery", lineage=lineage, run=run, era=era, generation="B", slots=slots,
                    validate=lambda o, era=era: _outside(c, era, _cited(o, ("sentence_ids",)))))
                store.write_json(artifacts.path_of(c.ws, f"discovery:{lineage}:{run}:{era}"), out)
                hypotheses += out["hypotheses"]
                store.write_text_atomic(artifacts.path_of(c.ws, f"hypotheses:{lineage}:{run}:{era}"),
                                        "".join(f"- {h}\n" for h in hypotheses) or "- (none)\n")


def _pool(c: Context) -> dict[str, dict]:
    """Every discovery candidate under an opaque ref; the map back to its rater stays local."""
    candidates = {}
    for lineage in c.cfg.lineages:
        for run in c.runs:
            for era in c.era_ids:
                for t in store.read_json(artifacts.path_of(c.ws, f"discovery:{lineage}:{run}:{era}"))["traits"]:
                    ref = f"c{len(candidates) + 1:03d}"
                    candidates[ref] = {"lineage": lineage, "run": run, "era": era, "trait": t["trait"],
                                       "alexander_id": t["alexander_id"]}
    store.write_json(c.ws.path("run/discovery/pool.json"), candidates)
    store.write_text_atomic(artifacts.path_of(c.ws, "pool:all"), "".join(
        f"{ref} | {cand['trait']} | {cand['alexander_id']}\n" for ref, cand in candidates.items()))
    return candidates


# --- codebook ----------------------------------------------------------------------------------------------------

def validate_codebook(out: dict, refs: set[str]) -> list[str]:
    """No always-compound marker in a name, unique ids, at most 80, and every candidate placed exactly once."""
    problems = []
    cons = out["constructs"]
    ids = [c["id"] for c in cons]
    if len(ids) != len(set(ids)):
        problems.append("duplicate construct ids")
    if len(cons) > MAX_CONSTRUCTS:
        problems.append(f"more than {MAX_CONSTRUCTS} constructs")
    problems += [f"{c['id']}: name is not atomic" for c in cons if COMPOUND_NAME.search(c["name"])]
    problems += [f"{c['id']}: traces no candidate" for c in cons if not c["trace"]]
    problems += [f"{c['id']}: a candidate repeats in its trace" for c in cons
                 if len(c["trace"]) != len(set(c["trace"]))]
    holders: dict[str, set[str]] = {}
    for c in cons:
        for ref in c["trace"]:
            holders.setdefault(ref, set()).add(c["id"])
    appendix: dict[str, str] = {}
    for a in out["appendix"]:
        if a["candidate_ref"] in appendix:
            problems.append(f"{a['candidate_ref']} appears twice in the appendix")
        appendix[a["candidate_ref"]] = a["disposition"]
    unknown = (set(holders) | set(appendix)) - refs
    if unknown:
        problems.append(f"{len(unknown)} unknown candidate ref(s)")
    for ref in sorted(refs):
        n, disp = len(holders.get(ref, ())), appendix.get(ref)
        placed = {None: n == 1, "merged": n == 1, "excluded": n == 0, "split": n >= 2}.get(disp, False)
        if not placed:
            problems.append(f"{ref} is not placed exactly once ({n} constructs, appendix {disp})")
    return problems


def item_id(construct_id: str, salt: str) -> str:
    return "K" + hashlib.sha256(f"{construct_id}|{salt}".encode()).hexdigest()[:6]


def _codebook(c: Context, candidates: dict[str, dict]) -> dict:
    salt = store.sha256_file(c.ws.path("prepare/redacted.txt"))

    def validate(o):
        problems = validate_codebook(o, set(candidates))
        ids = [item_id(con["id"], salt) for con in o["constructs"]]
        return problems + (["card item ids collide; the author must rename a construct"]
                           if len(set(ids)) != len(ids) else [])

    out = invoke.call(c.ws, c.cfg, invoke.CallRequest(
        stage="extract", role="codebook_author", lineage=c.cfg.codebook_author, run=None, era=None, generation="B",
        slots={"pool": "pool:all"}, validate=validate))
    constructs = [{**con, "lineages": sorted({candidates[ref]["lineage"] for ref in con["trace"]}),
                   "item_id": item_id(con["id"], salt)} for con in out["constructs"]]
    book = {"constructs": constructs, "appendix": out["appendix"]}
    store.write_json(c.ws.path("run/codebook/codebook.json"), book)
    store.write_text_atomic(artifacts.path_of(c.ws, "card:B"), "".join(
        card_line(con) for con in sorted(constructs, key=lambda x: x["item_id"])))
    return book


def card_line(construct: Mapping) -> str:
    """One card item as raters see it; the size check builds its largest possible card from this too."""
    return (f"- {construct['item_id']}: {construct['name']}. {construct['definition']} "
            f"Present when: {construct['sufficiency_rule']}\n")


# --- recode ------------------------------------------------------------------------------------------------------

def apply_bar(v: dict, seg_of) -> tuple[str, str | None]:
    """The script's verdict: present needs two occurrences in distinct, non-adjacent segments; absent a counter."""
    if v["verdict"] == "present":
        segs = [{seg_of(s) for s in occ["sentence_ids"]} for occ in v["occurrences"]]
        separate = any(all(abs(a - b) >= 2 for a in x for b in y) for i, x in enumerate(segs) for y in segs[i + 1:])
        return ("present", None) if separate else ("insufficient", "present_without_two_separate_episodes")
    if v["verdict"] == "absent":
        return ("absent", None) if v["counter_sentence_ids"] else ("insufficient", "absent_without_counter_sentence")
    return "insufficient", None


def _recode(c: Context, book: dict) -> None:
    items = {con["item_id"] for con in book["constructs"]}

    def seg_of(sid):
        return c.seg_index[c.sentences[sid]["segment_id"]]

    for lineage in c.cfg.lineages:
        for run in c.runs:
            for era in c.era_ids:

                def validate(o, era=era):
                    return _coverage(items, [v["item_id"] for v in o["verdicts"]]) or \
                        _outside(c, era, _cited(o, ("sentence_ids", "counter_sentence_ids")))

                out = invoke.call(c.ws, c.cfg, invoke.CallRequest(
                    stage="extract", role="recode", lineage=lineage, run=run, era=era, generation="C",
                    slots={"card": "card:B", "era": f"era:{era}"}, validate=validate))
                verdicts = []
                for v in out["verdicts"]:
                    final, reason = apply_bar(v, seg_of)
                    verdicts.append({"item_id": v["item_id"], "rater_verdict": v["verdict"], "verdict": final,
                                     "downgrade": reason})
                store.write_json(c.ws.path(f"run/recode/{lineage}-r{run}-{era}.json"),
                                 {"lineage": lineage, "run": run, "era": era, "verdicts": verdicts})


# --- deductive ---------------------------------------------------------------------------------------------------

def _deductive(c: Context) -> None:
    facets = sorted(c.facets)
    for lineage in c.cfg.lineages:
        for run in c.runs:
            ledgers, cited = [], {f: set() for f in facets}
            for era in c.era_ids:

                def validate(o, era=era):
                    if sorted(f["facet"] for f in o["facets"]) != facets:
                        return ["the ledger must list all 30 facets once"]
                    return _outside(c, era, _cited(o, ("sentence_ids",)))

                out = invoke.call(c.ws, c.cfg, invoke.CallRequest(
                    stage="extract", role="deductive_ledger", lineage=lineage, run=run, era=era, generation="C",
                    slots={"era": f"era:{era}", "facets": "facets:all"}, validate=validate))
                store.write_json(artifacts.path_of(c.ws, f"ledger:{lineage}:{run}:{era}"), out)
                ledgers.append({"era": era, **out})
                for entry in out["facets"]:
                    cited[entry["facet"]] |= set(_cited(entry, ("sentence_ids",)))
            store.write_json(artifacts.path_of(c.ws, f"ledgers:{lineage}:{run}"), ledgers)

            evidence = {f: frozenset(ids) for f, ids in cited.items()}

            def validate_scores(o, cited=evidence):
                """Each score rests on its own facet's ledger evidence; a facet with none must be insufficient."""
                if sorted(s["facet"] for s in o["scores"]) != facets:
                    return ["scores must cover all 30 facets once"]
                problems = []
                for s in o["scores"]:
                    if s["score"] is None:
                        continue
                    if not cited[s["facet"]]:
                        problems.append(f"{s['facet']}: scored without ledger evidence for that facet")
                    elif not s["cited_sentence_ids"] or not set(s["cited_sentence_ids"]) <= cited[s["facet"]]:
                        problems.append(f"{s['facet']}: citations must come from that facet's ledger evidence")
                return problems

            out = invoke.call(c.ws, c.cfg, invoke.CallRequest(
                stage="extract", role="deductive_scorer", lineage=lineage, run=run, era=None, generation="C",
                slots={"ledgers": f"ledgers:{lineage}:{run}", "facets": "facets:all"}, validate=validate_scores))
            store.write_json(c.ws.path(f"run/deductive/scores-{lineage}-r{run}.json"),
                             {"lineage": lineage, "run": run, "scores": out["scores"]})


# --- agreement ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Ratings:
    """The blind ratings as named records, read from the run files; the report's recomputation uses this too."""

    verdicts: Mapping[RaterKey, tuple[dict, ...]]
    scores: Mapping[RaterKey, Mapping[str, int | None]]


def load_ratings(ws: store.Workspace) -> Ratings:
    verdicts = {}
    for path in sorted(ws.root.glob("run/recode/*.json")):
        rec = store.read_json(path)
        verdicts[RaterKey(rec["lineage"], rec["run"], rec["era"])] = tuple(rec["verdicts"])
    scores = {}
    for path in sorted(ws.root.glob("run/deductive/scores-*.json")):
        rec = store.read_json(path)
        scores[RaterKey(rec["lineage"], rec["run"], None)] = MappingProxyType({s["facet"]: s["score"]
                                                                               for s in rec["scores"]})
    return Ratings(MappingProxyType(verdicts), MappingProxyType(scores))


def arms(ratings: Ratings, book: dict, era_ids: list[str],
         facets: list[str]) -> tuple[agreement.ArmResult, agreement.ArmResult]:
    """The inductive (constructs-only) and deductive (strict) arms, from named ratings. The inductive value asks
    whether the era shows the construct: absent and insufficient verdicts, after the citation rules, are both
    not_present."""
    units = [Unit(con["item_id"], era) for con in book["constructs"] for era in era_ids]
    runs: dict = {}
    for key, rows in ratings.verdicts.items():
        cell = runs.setdefault(key.lineage, {}).setdefault(key.run, {})
        for v in rows:
            cell[Unit(v["item_id"], key.era)] = "present" if v["verdict"] == "present" else "not_present"
    druns: dict = {}
    for key, by_facet in ratings.scores.items():
        druns.setdefault(key.lineage, {})[key.run] = by_facet
    return agreement.arm(runs, units, "nominal"), agreement.arm(druns, facets, "ordinal")


def _arm_json(arm: agreement.ArmResult) -> dict:
    return {"metric": arm.metric, "alpha": arm.alpha, "verdict": arm.verdict, "reason": arm.reason,
            "paired_fraction": arm.paired_fraction, "raw_agreement": arm.raw_agreement,
            "missing_rate": arm.missing_rate, "stability": {lin: arm.stability[lin] for lin in sorted(arm.stability)},
            "units": len(arm.units), "integrity_audit_due": arm.integrity_audit_due}


def _agree(c: Context, book: dict) -> dict:
    ratings = load_ratings(c.ws)
    inductive, deductive_arm = arms(ratings, book, c.era_ids, list(c.facets))
    lineages = sorted(inductive.collapsed)
    result = {
        "inductive": _arm_json(inductive), "deductive": _arm_json(deductive_arm),
        "construct_status": {con["id"]: {era: agreement.status([inductive.collapsed[lin][Unit(con["item_id"], era)]
                                                               for lin in lineages]) for era in c.era_ids}
                             for con in book["constructs"]},
        "inductive_collapsed": [{"lineage": lin, "item_id": u.item_id, "era": u.era, "value": v}
                                for lin in lineages for u, v in inductive.collapsed[lin].items()],
        "deductive_collapsed": [{"lineage": lin, "facet": f, "value": v} for lin in sorted(deductive_arm.collapsed)
                                for f, v in deductive_arm.collapsed[lin].items()],
        "downgrades": sum(1 for rows in ratings.verdicts.values() for v in rows if v["downgrade"]),
    }
    if inductive.integrity_audit_due or deductive_arm.integrity_audit_due:
        result["integrity_audit"] = integrity_audit(c)
        if not all(check["ok"] for check in result["integrity_audit"].values()):
            store.write_json(c.ws.path("run/agreement.json"), result)
            raise IntegrityError("integrity audit failed after very high agreement; results invalidated")
    store.write_json(c.ws.path("run/agreement.json"), result)
    return result


def integrity_audit(c: Context) -> dict:
    """Requalify, then re-audit every call record's events and inputs, and the manifest chain."""
    records = sorted(c.ws.root.glob("run/calls/**/*.json"))
    Check = agreement.Check

    def requalify():
        fresh = qualify.qualify(c.ws, c.cfg, out=REQUALIFICATION_AUDIT)
        baseline = invoke.qualified(c.ws)
        moved = [lin for lin, q in fresh.items()
                 if any(q.get(k) != baseline[lin].get(k) for k in invoke.FINGERPRINT_KEYS)]
        return Check(not moved, "fingerprint_moved" if moved else "requalified", {"lineages_moved": len(moved)})

    def events():
        def tool_events(path):
            rec = store.read_json(path)
            evs = invoke.decode_events(rec.get("events"))
            if evs is None:
                return ["unreadable"]
            state = invoke.outcome(rec["lineage"], rec.get("exit"), evs)
            return [] if state == "success" else [state]

        hits = sum(1 for p in records if tool_events(p))
        incidents = sum(1 for p in sorted(c.ws.root.glob("run/incidents/**/*.json"))
                        if store.read_json(p)["kind"] == "tool_event")
        ok = not hits and not incidents
        return Check(ok, "clean" if ok else "tool_events",
                     {"records": len(records), "records_with_tool_events": hits, "tool_event_incidents": incidents})

    def allowlists():
        outside = 0
        for path in records:
            rec = store.read_json(path)
            rater = (rec["lineage"], rec["run"]) if rec["run"] is not None else None
            try:
                prompts.check_allowlist(rec["role"], list(rec["input_artifacts"]), rater=rater, era=rec["era"],
                                        era_order=c.era_ids)
            except AbxError:
                outside += 1
        return Check(not outside, "within_allowlists" if not outside else "outside_allowlist",
                     {"records": len(records), "outside": outside})

    def manifest():
        return Check(True, "verified", {"generations": len(store.verify_manifest(c.ws))})

    return agreement.integrity_audit({"requalify": requalify, "events": events, "allowlist": allowlists,
                                      "manifest": manifest})


def extract(ws: store.Workspace) -> dict:
    gens = lifecycle.enter(ws, STAGE)
    invoke.check_method(ws)
    c = _context(ws)
    if "B" not in gens:
        _discovery(c)
        candidates = _pool(c)
        _codebook(c, candidates)
        store.append_generation(ws, "B", [
            "run/discovery/pool.json", "run/discovery/pool.md", "run/codebook/codebook.json", "run/codebook/card.md",
            *(ws.rel(p) for g in ("run/discovery/*-r*-*.json", "run/discovery/*.hypotheses.md",
                                  "run/calls/extract/discovery/*.json", "run/calls/extract/codebook_author/*.json")
              for p in sorted(ws.root.glob(g)))])
    if "C" in gens:
        return store.read_json(ws.path("run/agreement.json"))
    book = store.read_json(ws.path("run/codebook/codebook.json"))
    _recode(c, book)
    _deductive(c)
    result = _agree(c, book)
    outputs = [ws.rel(p) for g in ("run/recode/*.json", "run/deductive/*.json", "run/calls/extract/recode/*.json",
                                   "run/calls/extract/deductive_*/*.json", REQUALIFICATION_AUDIT,
                                   "run/incidents/prepare/**/*.json", "run/incidents/extract/**/*.json")
               for p in sorted(ws.root.glob(g))]
    store.append_generation(ws, "C", ["run/agreement.json", *outputs])
    return result


STAGE = lifecycle.Stage("extract", 4, "the blind engine, to generation C", extract, estimate, needs="A",
                        closed_after="E")
