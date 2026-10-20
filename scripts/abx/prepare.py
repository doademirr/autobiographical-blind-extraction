"""`prepare`: local redaction and eras (review point 1), qualification, zoning, the substrate."""

import shutil
from pathlib import Path

from . import artifacts, config, invoke, ipip, lifecycle, qualify, store, text, withheld
from .errors import UsageError
from .roles import ROLES

__all__ = ["RECEIPT", "STAGE", "estimate", "prepare", "receipt_problems", "review_doc"]

RECEIPT = "prepare/receipt.json"
RECEIPT_INPUTS = ("text/original.txt", "config.json", "prepare/redactions.json", "prepare/eras.json",
                  "prereg/prompts/zoner.md", "prereg/schemas/zoner.json")
RECEIPT_OUTPUT_GLOBS = ("prepare/redacted.txt", "prepare/offsets.json", "prepare/segments.json",
                        "prepare/sentences.json", "prepare/stats.json", "prepare/removed-sentences.json",
                        "prepare/substrate/*.md", "prepare/chunks/*/*.txt", "prepare/zoning/*.json")

REPO = Path(__file__).resolve().parents[2]
THIN, STOP = 0.50, 0.25
# The most hypotheses text one earlier era can pass to discovery: the schema allows 40 of 300 characters,
# plus list markers. Era k carries the hypotheses of every era before it.
MAX_HYPOTHESES_CHARS = 40 * 303


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


def _review_files(ws: store.Workspace, original: str) -> dict[str, tuple[dict, str]] | None:
    """Write the templates the user edits on first run. Returns each review file read exactly once, as
    (parsed document, sha256 of the bytes read), when both are approved; None while either is not.
    Preparation uses only this snapshot, so a file edited mid-run cannot change what was approved."""
    red, eras = ws.path("prepare/redactions.json"), ws.path("prepare/eras.json")
    if not red.exists():
        store.write_json(red, {"approved": False, "names": {}})
    if not eras.exists():
        segs = text.segment(original)
        store.write_json(eras, {"approved": False, "eras": [
            {"id": "e1", "label": "", "date_range": "", "segment_ids": [s.id for s in segs]}]})
        preview = [f"{s.id}: {original[s.start:s.end][:100]}" for s in segs]
        store.write_text_atomic(ws.path("prepare/segments-preview.txt"), "\n".join(preview) + "\n")
    snapshot = {}
    for name in ("redactions.json", "eras.json"):
        raw = ws.path(f"prepare/{name}").read_bytes()
        snapshot[name] = (_parse_review(name, raw), store.sha256_bytes(raw))
    return snapshot if all(doc["approved"] is True for doc, _ in snapshot.values()) else None


def review_doc(ws: store.Workspace, name: str) -> dict:
    """A review file, parsed whole: an object with `approved` and its list or mapping, else a usage error."""
    return _parse_review(name, ws.path(f"prepare/{name}").read_bytes())


def _parse_review(name: str, raw: bytes) -> dict:
    try:
        doc = store.loads_strict(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UsageError(f"{name} is not valid JSON") from exc
    key, kind = ("names", dict) if name == "redactions.json" else ("eras", list)
    if not isinstance(doc, dict) or not isinstance(doc.get(key), kind) or not isinstance(doc.get("approved"), bool):
        raise UsageError(f"{name}: expected an object with \"approved\" (true or false) and \"{key}\"")
    return doc


def estimate(ws: store.Workspace) -> lifecycle.Preflight:
    eras = review_doc(ws, "eras.json")["eras"] if ws.path("prepare/eras.json").exists() else []
    original = ws.path("text/original.txt").read_text(encoding="utf-8")
    sents = text.sentences(original, text.segment(original))
    chunks = sum(len(text.zoning_chunks([s for s in sents if s.segment_id in set(e.get("segment_ids", []))]))
                 for e in eras if isinstance(e, dict))
    return lifecycle.Preflight(chunks + 2, 0, f"one zoning call per chunk of up to {text.ZONING_CHUNK} sentences "
                                              "plus one leak probe per lineage")


def _zone(ws: store.Workspace, cfg: config.Config, era: dict, sents: list[text.Sentence],
          redacted: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for part, chunk in enumerate(text.zoning_chunks(sents), start=1):
        aid = f"chunk:{era['id']}:{part}"
        store.write_text_atomic(artifacts.path_of(ws, aid), text.render_numbered(redacted, chunk) + "\n")
        expected = {s.id for s in chunk}

        def validate(out, expected=expected) -> list[str]:
            got = [lab["sentence_id"] for lab in out["labels"]]
            if len(got) != len(set(got)) or set(got) != expected:
                return [f"labels must cover the chunk's {len(expected)} sentence ids exactly once"]
            return []

        req = invoke.CallRequest(stage="prepare", role="zoner", lineage=cfg.zoner, run=None, era=era["id"],
                                 generation="A", slots={"chunk": aid}, validate=validate, part=part)
        labels |= {lab["sentence_id"]: lab["label"] for lab in invoke.call(ws, cfg, req)["labels"]}
    return labels


def prepare(ws: store.Workspace) -> dict:
    lifecycle.enter(ws, STAGE)
    cfg = config.load(ws)
    original = ws.path("text/original.txt").read_text(encoding="utf-8")
    snapshot = _review_files(ws, original)
    if snapshot is None:
        return {"status": "review", "next": "approve_review_files"}
    names = snapshot["redactions.json"][0]["names"]
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in names.items()):
        raise UsageError("redactions.json: names must map each name to its replacement text")
    eras = snapshot["eras.json"][0]["eras"]
    if not all(isinstance(e, dict) for e in eras):
        raise UsageError("eras.json: eras must be a list of era objects")
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
    return _substrate(ws, cfg, eras, sents, redacted, labels, {f"prepare/{n}": h for n, (_, h) in snapshot.items()})


def _substrate(ws, cfg: config.Config, eras, sents, redacted, labels, approved: dict[str, str]) -> dict:
    kept = {sid for sid, lab in labels.items() if lab == "keep"}
    kept_text = {redacted[s.start:s.end] for s in sents if s.id in kept}
    removed = [redacted[s.start:s.end] for s in sents if s.id not in kept]
    store.write_json(ws.path(withheld.REMOVED),
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
            fixed = template.read_text() + ws.path(f"prereg/schemas/{policy.schema}.json").read_text() + body
            if "facets" in policy.kinds:
                fixed += ws.path("prereg/facets.md").read_text()
            if "hypotheses" in policy.kinds:
                fixed += "x" * (MAX_HYPOTHESES_CHARS * eras.index(era))
            fixed += era["label"] or era["id"]
            need = invoke.estimate_tokens(fixed)
            for lin in cfg.lineages.values():
                if need + lin.reserve_output_tokens > lin.input_budget_tokens:
                    raise UsageError(f"era {era['id']} is too large for {policy.name} on {lin.name}")
    store.write_json(ws.path("prepare/stats.json"), stats)
    receipt = _receipt(ws)
    changed = [rel for rel, digest in approved.items() if receipt[rel] != digest]
    if changed:
        raise UsageError(f"{', '.join(changed)} changed while `prepare` ran; rerun it")
    store.write_json(ws.path(RECEIPT), receipt)
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


STAGE = lifecycle.Stage("prepare", 1, "redaction and eras review, qualification, zoning", prepare, estimate,
                        closed_after="A", verifies_seal=False)
