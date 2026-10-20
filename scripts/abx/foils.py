"""Foils: known-answer card items, authored blind per era at `freeze`, diagnostic only.

A clean-room author sees one zoned era and writes one to three items, each of a type whose
evidence the script checks against that era's sentences. A foil's expectation covers its own
era only; on the card it looks like a construct (`card`). The auditor's view of an era's foils
is rendered here from the frozen JSON, so the two can never disagree.
"""

from pathlib import Path

from . import artifacts, card, config, evidence, invoke, store

__all__ = ["EXPECTED", "MAX_FOILS", "author", "load", "path", "render_for_audit", "validate"]

# What each type expects in its own era.
EXPECTED = {"clear": "absent", "near_miss": "absent", "anchored": "present"}
MAX_FOILS = 3  # per era, the foils schema's maxItems


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
            evidence.apply_bar({"verdict": "present", "occurrences": support}, ix.seg_of)[0] != "present":
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


def render_for_audit(foils: list[dict], era: str) -> str:
    """The auditor's view: type, expectation and card text, without the author's citations, so the auditor reads the
    era itself."""
    return "".join(f"- {f['id']} ({f['type']}, expected {f['expected'][era]} in this era): {f['name']}. "
                   f"{f['definition']} Present when: {f['sufficiency_rule']}\n" for f in foils) or "- (none)\n"


def author(ws: store.Workspace, cfg: config.Config, ix: evidence.Index, salt: str) -> None:
    """One foil-author call per era; each era's foils are stored with their expectation and card item id."""
    for era in ix.era_ids:
        out = invoke.call(ws, cfg, invoke.CallRequest(
            stage="freeze", role="foil_author", lineage=cfg.foil_author, run=None, era=era, generation="A",
            slots={"era": f"era:{era}"}, validate=lambda o, era=era: validate(o, ix, era)))
        foils = [{**f, "expected": {era: EXPECTED[f["type"]]}, "item_id": card.item_id(f"foil:{era}:{f['id']}", salt)}
                 for f in out["foils"]]
        store.write_json(path(ws, era), {"era": era, "foils": foils})
        store.write_text_atomic(artifacts.path_of(ws, f"foils:{era}"), render_for_audit(foils, era))
