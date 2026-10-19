"""`prepare`: local redaction and eras (review point 1), qualification, zoning, the substrate."""

import shutil
from pathlib import Path

from . import artifacts, config, invoke, ipip, lifecycle, qualify, store, text, withheld
from .errors import UsageError
from .roles import ROLES

__all__ = ["RECEIPT", "estimate", "prepare", "receipt_problems"]

RECEIPT = "prepare/receipt.json"
RECEIPT_INPUTS = ("text/original.txt", "config.json", "prepare/redactions.json", "prepare/eras.json",
                  "prereg/prompts/zoner.md", "prereg/schemas/zoner.json")
RECEIPT_OUTPUT_GLOBS = ("prepare/redacted.txt", "prepare/segments.json", "prepare/sentences.json", "prepare/stats.json",
                        "prepare/substrate/*.md", "prepare/chunks/*.txt", "prepare/zoning/*.json")

REPO = Path(__file__).resolve().parents[2]
THIN, STOP = 0.50, 0.25


def _stage_method(ws: store.Workspace) -> None:
    """Copy the repo's prompts, schemas and IPIP instrument in, and derive the facet catalog raters see
    (codes and names only, never questionnaire items); freeze hashes them all in generation A."""
    for name in ("prompts", "schemas"):
        if not ws.path(f"prereg/{name}").exists():
            shutil.copytree(REPO / name, ws.path(f"prereg/{name}"))
    if not ws.path(ipip.FROZEN_COPY).exists():
        ws.path(ipip.FROZEN_COPY).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ipip.INSTRUMENT, ws.path(ipip.FROZEN_COPY))
    facets = ipip.load_instrument(ws)["facets"]
    store.write_text_atomic(artifacts.path_of(ws, "facets:all"), "".join(f"- {c} {n}\n" for c, n in facets.items()))
    for name, path in (("ledger", ("facets", "items", "properties", "facet")),
                       ("scores", ("scores", "items", "properties", "facet"))):
        schema_path = ws.path(f"prereg/schemas/{name}.json")
        schema = store.read_json(schema_path)
        node = schema["properties"]
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = {"type": "string", "enum": sorted(facets)}
        store.write_json(schema_path, schema)


def _review_files(ws: store.Workspace, original: str) -> bool:
    """Write the templates the user edits; True when both are present and approved."""
    red, eras = ws.path("prepare/redactions.json"), ws.path("prepare/eras.json")
    if not red.exists():
        store.write_json(red, {"approved": False, "names": {}})
    if not eras.exists():
        segs = text.segment(original)
        store.write_json(eras, {"approved": False, "eras": [
            {"id": "e1", "label": "", "date_range": "", "segment_ids": [s.id for s in segs]}]})
        preview = [f"{s.id}: {original[s.start:s.end][:100]}" for s in segs]
        store.write_text_atomic(ws.path("prepare/segments-preview.txt"), "\n".join(preview) + "\n")
    return store.read_json(red).get("approved") is True and store.read_json(eras).get("approved") is True


def estimate(ws: store.Workspace) -> lifecycle.Preflight:
    eras = ws.path("prepare/eras.json")
    n = len(store.read_json(eras)["eras"]) if eras.exists() else 0
    return lifecycle.Preflight(n + 2, 0, "one zoning call per era plus one leak probe per lineage")


def _zone(ws: store.Workspace, cfg: config.Config, era: dict, sents: list[text.Sentence],
          redacted: str) -> dict[str, str]:
    store.write_text_atomic(artifacts.path_of(ws, f"chunk:{era['id']}"), text.render_numbered(redacted, sents) + "\n")
    expected = {s.id for s in sents}

    def validate(out) -> list[str]:
        got = [lab["sentence_id"] for lab in out["labels"]]
        if len(got) != len(set(got)) or set(got) != expected:
            return [f"labels must cover the chunk's {len(expected)} sentence ids exactly once"]
        return []

    req = invoke.CallRequest(stage="prepare", role="zoner", lineage=cfg.zoner, run=None, era=era["id"],
                             generation="A", slots={"chunk": f"chunk:{era['id']}"}, validate=validate)
    out = invoke.call(ws, cfg, req)
    return {lab["sentence_id"]: lab["label"] for lab in out["labels"]}


def prepare(ws: store.Workspace) -> dict:
    lifecycle.enter(ws, "prepare")
    cfg = config.load(ws)
    original = ws.path("text/original.txt").read_text(encoding="utf-8")
    if not _review_files(ws, original):
        return {"status": "review", "next": "approve_review_files"}
    names = store.read_json(ws.path("prepare/redactions.json"))["names"]
    eras = store.read_json(ws.path("prepare/eras.json"))["eras"]
    redacted, spans = text.redact(original, names)
    segs = text.segment(redacted)
    sents = text.sentences(redacted, segs)
    text.validate_eras(eras, segs)
    store.write_text_atomic(ws.path("prepare/redacted.txt"), redacted)
    store.write_json(ws.path("prepare/offsets.json"), spans)
    store.write_json(ws.path("prepare/segments.json"), text.as_dicts(segs))
    store.write_json(ws.path("prepare/sentences.json"), text.as_dicts(sents))
    _stage_method(ws)
    if not ws.path(invoke.QUALIFICATION).exists():
        qualify.qualify(ws, cfg)
    labels: dict[str, str] = {}
    for era in eras:
        era_sents = [s for s in sents if s.segment_id in set(era["segment_ids"])]
        labels |= _zone(ws, cfg, era, era_sents, redacted)
        store.write_json(ws.path(f"prepare/zoning/{era['id']}.json"),
                         {sid: labels[sid] for sid in (s.id for s in era_sents)})
    return _substrate(ws, cfg, eras, sents, redacted, labels)


def _substrate(ws, cfg: config.Config, eras, sents, redacted, labels) -> dict:
    kept = {sid for sid, lab in labels.items() if lab == "keep"}
    kept_text = {redacted[s.start:s.end] for s in sents if s.id in kept}
    removed = [redacted[s.start:s.end] for s in sents if s.id not in kept]
    store.write_json(ws.path("prepare/zoning/removed.json"),
                     [r for r in removed if len(r) >= withheld.MIN_REMOVED_LEN and r not in kept_text])
    store.write_text_atomic(ws.path("prepare/retrospective.md"), "".join(
        f"[{s.id}] ({labels[s.id]}) {redacted[s.start:s.end]}\n" for s in sents if s.id not in kept))
    stats = {}
    for era in eras:
        era_sents = [s for s in sents if s.segment_id in set(era["segment_ids"])]
        body = text.render_zoned(redacted, era["segment_ids"], era_sents, kept)
        store.write_text_atomic(artifacts.path_of(ws, f"era:{era['id']}"), body)
        total = sum(len(redacted[s.start:s.end].split()) for s in era_sents)
        kept_words = sum(len(redacted[s.start:s.end].split()) for s in era_sents if s.id in kept)
        ratio = kept_words / total if total else 0.0
        stats[era["id"]] = {
            "sentences": len(era_sents), "segments": len(era["segment_ids"]), "words": total,
            "kept_words": kept_words, "kept_ratio": ratio,
            "mixed": sum(1 for s in era_sents if labels[s.id] == "mixed"),
            "removed": sum(1 for s in era_sents if labels[s.id] == "remove"),
            "band": "normal" if ratio >= THIN else "thin" if ratio >= STOP else "stop",
        }
        for policy in ROLES.values():
            template = ws.path(f"prereg/prompts/{policy.name}.md")
            if not (policy.per_era and policy.name != "zoner" and template.exists()):
                continue
            need = invoke.estimate_tokens(template.read_text() + body)
            for lin in cfg.lineages.values():
                if need + lin.reserve_output_tokens > lin.input_budget_tokens:
                    raise UsageError(f"era {era['id']} is too large for {policy.name} on {lin.name}")
    store.write_json(ws.path("prepare/stats.json"), stats)
    store.write_json(ws.path(RECEIPT), _receipt(ws))
    return {"status": "done", "stats": stats}


def _receipt(ws: store.Workspace) -> dict:
    """Hashes of what this preparation read and wrote, so a later edit to either is caught at `freeze`."""
    outputs = [ws.rel(p) for g in RECEIPT_OUTPUT_GLOBS for p in sorted(ws.root.glob(g))]
    return {rel: store.sha256_file(ws.path(rel)) for rel in (*RECEIPT_INPUTS, *outputs)}


def receipt_problems(ws: store.Workspace) -> list[str]:
    """Inputs or outputs that changed since `prepare` last finished; empty when preparation is current."""
    if not ws.path(RECEIPT).exists():
        return ["`prepare` has not finished"]
    recorded, current = store.read_json(ws.path(RECEIPT)), _receipt(ws)
    return sorted(rel for rel in set(recorded) | set(current) if recorded.get(rel) != current.get(rel))


STAGE = lifecycle.Stage("prepare", 1, "redaction and eras review, qualification, zoning", prepare, estimate)
