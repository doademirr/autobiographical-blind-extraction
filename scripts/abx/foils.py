"""Foils: known-answer card items, authored blind per era at `freeze`, diagnostic only.

A clean-room author sees one zoned era and writes one to three items, each of a type whose
evidence the script checks against that era's sentences. A foil's expectation covers its own
era only; on the card it looks like a construct (`card`). The auditor's view of an era's foils
is rendered here from the frozen JSON, so the two can never disagree.
"""

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from . import artifacts, card, config, evidence, invoke, store

__all__ = ["EXPECTED", "author", "endorsement", "load", "path", "render_for_audit", "validate"]

# What each type expects in its own era.
EXPECTED = MappingProxyType({"clear": "absent", "near_miss": "absent", "anchored": "present"})


def path(ws: store.Workspace, era: str) -> Path:
    return ws.path(f"prereg/foils/{era}.json")


def load(ws: store.Workspace, era: str) -> list[dict]:
    return store.read_json(path(ws, era))["foils"]


def _evidence_problems(foil: dict, ix: evidence.Index) -> list[str]:
    support, counter = foil["support"], foil["counter_sentence_ids"]
    if foil["type"] == "clear" and (support or not counter):
        return [f"{foil['id']}: a clear foil cites at least one counter-sentence and no support"]
    if foil["type"] == "near_miss" and not (support and counter):
        return [f"{foil['id']}: a near-miss foil cites a tempting support occurrence and a counter-sentence"]
    if foil["type"] == "anchored" and \
            evidence.apply_bar({"verdict": "present", "occurrences": support}, ix.seg_of).verdict != "present":
        return [f"{foil['id']}: an anchored foil cites two support occurrences in separate, non-adjacent paragraphs"]
    return []


def validate(out: dict, ix: evidence.Index, era: str) -> list[str]:
    """Citations inside the zoned era first (the recurrence check needs known sentences), then ids, names and each
    type's evidence rule."""
    stray = ix.outside(era, evidence.cited(out, ("sentence_ids", "counter_sentence_ids")))
    if stray:
        return stray
    foils = out["foils"]
    ids = [f["id"] for f in foils]
    problems = ["foil ids repeat"] if len(ids) != len(set(ids)) else []
    problems += [f"{f['id']}: name is not atomic" for f in foils if card.COMPOUND_NAME.search(f["name"])]
    return problems + [p for f in foils for p in _evidence_problems(f, ix)]


def endorsement(verdicts: Mapping, kept: list[dict], lineages: list[str]) -> dict:
    """Per type and lineage, the share of rater-run verdicts (after the citation rules) in each kept foil's own era
    that are present: the recovery rate for anchored foils, the false-positive rate for the others. `verdicts` maps
    rater keys (with `lineage` and `era`) to verdict rows. A type with no verdicts has rate None; types never blend."""
    out = {t: {"items": 0, "by_lineage": {lin: {"verdicts": 0, "present": 0} for lin in lineages}} for t in EXPECTED}
    for f in kept:
        out[f["type"]]["items"] += 1
        for key, rows in verdicts.items():
            if key.era != f["era"]:
                continue
            cell = out[f["type"]]["by_lineage"][key.lineage]
            for v in rows:
                if v["item_id"] == f["item_id"]:
                    cell["verdicts"] += 1
                    cell["present"] += v["verdict"] == "present"
    for t in out.values():
        for cell in t["by_lineage"].values():
            cell["rate"] = cell["present"] / cell["verdicts"] if cell["verdicts"] else None
    return out


def render_for_audit(foils: list[dict], era: str) -> str:
    """The auditor's view: type, expectation and card text, without the author's citations, so the auditor reads the
    era itself."""
    return "".join(f"- {f['id']} ({f['type']}, expected {f['expected'][era]} in this era): {f['name']}. "
                   f"{f['definition']} Present when: {f['sufficiency_rule']}\n" for f in foils) or "- (none)\n"


def _free_id(key: str, salt: str, taken: set[str]) -> str:
    n = 0
    while (iid := card.item_id(key if n == 0 else f"{key}:{n}", salt)) in taken:
        n += 1
    taken.add(iid)
    return iid


def author(ws: store.Workspace, cfg: config.Config, ix: evidence.Index, salt: str) -> None:
    """One foil-author call per era; each era's foils are stored with their expectation and card item id. Item ids
    are unique across eras by construction: a hash collision with an earlier foil takes the next free suffix."""
    taken: set[str] = set()
    for era in ix.era_ids:
        out = invoke.call(ws, cfg, invoke.CallRequest(
            stage="freeze", role="foil_author", lineage=cfg.foil_author, run=None, era=era, generation="A",
            slots={"era": f"era:{era}"}, validate=lambda o, era=era: validate(o, ix, era)))
        foils = [{**f, "expected": {era: EXPECTED[f["type"]]},
                  "item_id": _free_id(f"foil:{era}:{f['id']}", salt, taken)} for f in out["foils"]]
        store.write_json(path(ws, era), {"era": era, "foils": foils})
        store.write_text_atomic(artifacts.path_of(ws, f"foils:{era}"), render_for_audit(foils, era))
