"""The blind audit: one clean-room call per era, on the auditor lineage, before the card is built.

The auditor reads the whole zoned era against the codebook's constructs and the foils authored
from that era. It drops foils whose expectation it judges unclear, and flags constructs the era
holds uncited counter-evidence against. Flags are reported, never acted on: a construct
contradicted in one era may be shown in another, which is what recode measures.
"""

from collections.abc import Mapping

from . import artifacts, config, evidence, foils, invoke, store

__all__ = ["FOILS", "render_codebook", "run", "validate"]

FOILS = "run/codebook/foils.json"  # the foils that reach the card, and those the audit dropped


def render_codebook(constructs: list[Mapping]) -> str:
    """The auditor's view of the codebook: each construct's id and card text."""
    return "".join(f"- {c['id']}: {c['name']}. {c['definition']} Present when: {c['sufficiency_rule']}\n"
                   for c in constructs)


def validate(out: dict, ix: evidence.Index, era: str, foil_ids: list[str], construct_ids: set[str]) -> list[str]:
    """Every foil of the era decided exactly once; each flag names a known construct once and cites the era."""
    decided = [d["foil_id"] for d in out["foils"]]
    problems = [] if sorted(decided) == sorted(foil_ids) else \
        [f"decide each of this era's test items exactly once ({', '.join(foil_ids) or 'none'})"]
    flagged = [f["construct_id"] for f in out["flags"]]
    problems += [f"{cid} is not in the codebook" for cid in sorted(set(flagged) - construct_ids)]
    if len(flagged) != len(set(flagged)):
        problems.append("a construct is flagged more than once")
    return problems + ix.outside(era, evidence.cited(out, ("counter_sentence_ids",)))


def run(ws: store.Workspace, cfg: config.Config, ix: evidence.Index, constructs: list[Mapping]) -> dict:
    """Audit every era; write each era's audit and the kept and dropped foils. Returns the kept foils."""
    store.write_text_atomic(artifacts.path_of(ws, "codebook:B"), render_codebook(constructs))
    construct_ids = {c["id"] for c in constructs}
    kept, dropped = [], []
    for era in ix.era_ids:
        authored = foils.load(ws, era)
        ids = [f["id"] for f in authored]
        out = invoke.call(ws, cfg, invoke.CallRequest(
            stage="extract", role="auditor", lineage=cfg.auditor, run=None, era=era, generation="B",
            slots={"foils": f"foils:{era}", "codebook": "codebook:B", "era": f"era:{era}"},
            validate=lambda o, era=era, ids=ids: validate(o, ix, era, ids, construct_ids)))
        store.write_json(ws.path(f"run/audit/{era}.json"), {"era": era, **out})
        drop = {d["foil_id"]: d["reason"] for d in out["foils"] if d["decision"] == "drop"}
        kept += [{**f, "era": era} for f in authored if f["id"] not in drop]
        dropped += [{"era": era, "id": fid, "reason": reason} for fid, reason in sorted(drop.items())]
    store.write_json(ws.path(FOILS), {"kept": kept, "dropped": dropped})
    return {"kept": kept, "dropped": dropped}
