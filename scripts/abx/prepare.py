"""`prepare`: local redaction and eras (review point 1), qualification, zoning, the substrate."""

import re
import shutil
from pathlib import Path

from . import artifacts, invoke, prompts, qualify, store, text
from .errors import UsageError

REPO = Path(__file__).resolve().parents[2]
PER_ERA_ROLES = ("discovery", "recode", "deductive_ledger")
THIN, STOP = 0.50, 0.25


def stage_method(ws: store.Workspace) -> None:
    """Copy the repo's prompts and schemas into the workspace; freeze hashes them in generation A."""
    for name in ("prompts", "schemas"):
        dest = ws.path(f"prereg/{name}")
        if not dest.exists():
            shutil.copytree(REPO / name, dest)


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


def load_secrets(ws: store.Workspace) -> prompts.Secrets:
    """Everything no prompt may carry, read only for this substring check."""
    s = prompts.Secrets(redacted_names=list(store.read_json(ws.path("prepare/redactions.json"))["names"]))
    retro = ws.path("prepare/zoning/removed.json")
    if retro.exists():
        s.removed_sentences = store.read_json(retro)
    pred = ws.path("sealed/self-prediction.md")
    if pred.exists():
        s.self_prediction = [m.group(1).strip() for m in re.finditer(r"^P\d+:(.+)$", pred.read_text(), re.M)
                             if len(m.group(1).strip()) >= 12]
    answers = ws.path("sealed/ipip-120.csv")
    if answers.exists():
        s.ipip = [line for line in answers.read_text().splitlines()[1:] if re.fullmatch(r"i\d{3},[1-5]", line)]
    return s


def _zone(ws: store.Workspace, cfg: dict, qual: dict, era: dict, sents: list[text.Sentence],
          redacted: str, secrets: prompts.Secrets) -> dict[str, str]:
    store.write_text_atomic(artifacts.path_of(ws, f"chunk:{era['id']}"), text.render_numbered(redacted, sents) + "\n")
    lineage = cfg["roles"]["zoner"]
    prompt = prompts.assemble("zoner", {"chunk": f"chunk:{era['id']}", "schema": "schema:zoner"},
                              artifacts.resolver(ws), {"era_label": era["label"] or era["id"]}, era=era["id"])
    prompts.audit(prompt, secrets)
    expected = {s.id for s in sents}

    def validate(out) -> list[str]:
        got = [lab["sentence_id"] for lab in out["labels"]]
        if len(got) != len(set(got)) or set(got) != expected:
            return [f"labels must cover the chunk's {len(expected)} sentence ids exactly once"]
        return []

    spec = invoke.CallSpec(stage="prepare", role="zoner", lineage=lineage, run=None, era=era["id"], generation="A",
                           schema_name="zoner", prompt=prompt, validate=validate)
    out = invoke.call(ws, cfg, spec, qual[lineage])
    return {lab["sentence_id"]: lab["label"] for lab in out["labels"]}


def _words(s: str) -> int:
    return len(s.split())


def prepare(ws: store.Workspace) -> dict:
    cfg = store.read_json(ws.path("config.json"))
    original = ws.path("text/original.txt").read_text(encoding="utf-8")
    if not _review_files(ws, original):
        return {"status": "review", "next": "edit and approve prepare/redactions.json and prepare/eras.json"}
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
    stage_method(ws)

    qual = qualify.qualify(ws, cfg) if not ws.path("run/qualification.json").exists() else qualify.qualified(ws)
    secrets = load_secrets(ws)
    labels: dict[str, str] = {}
    for era in eras:
        era_sents = [s for s in sents if s.segment_id in set(era["segment_ids"])]
        labels |= _zone(ws, cfg, qual, era, era_sents, redacted, secrets)
        store.write_json(ws.path(f"prepare/zoning/{era['id']}.json"),
                         {sid: labels[sid] for sid in (s.id for s in era_sents)})
    return build_substrate(ws, cfg, eras, sents, redacted, labels)


def build_substrate(ws, cfg, eras, sents, redacted, labels) -> dict:
    kept = {sid for sid, lab in labels.items() if lab == "keep"}
    kept_text = {redacted[s.start:s.end] for s in sents if s.id in kept}
    removed = [redacted[s.start:s.end] for s in sents if s.id not in kept]
    store.write_json(ws.path("prepare/zoning/removed.json"),
                     [r for r in removed if len(r) >= prompts.MIN_REMOVED_LEN and r not in kept_text])
    store.write_text_atomic(ws.path("prepare/retrospective.md"), "".join(
        f"[{s.id}] ({labels[s.id]}) {redacted[s.start:s.end]}\n" for s in sents if s.id not in kept))
    stats = {}
    for era in eras:
        era_sents = [s for s in sents if s.segment_id in set(era["segment_ids"])]
        body = text.render_zoned(redacted, era["segment_ids"], era_sents, kept)
        store.write_text_atomic(artifacts.path_of(ws, f"era:{era['id']}"), body)
        total = sum(_words(redacted[s.start:s.end]) for s in era_sents)
        kept_words = sum(_words(redacted[s.start:s.end]) for s in era_sents if s.id in kept)
        ratio = kept_words / total if total else 0.0
        stats[era["id"]] = {
            "sentences": len(era_sents), "segments": len(era["segment_ids"]), "words": total,
            "kept_words": kept_words, "kept_ratio": ratio,
            "mixed": sum(1 for s in era_sents if labels[s.id] == "mixed"),
            "removed": sum(1 for s in era_sents if labels[s.id] == "remove"),
            "band": "normal" if ratio >= THIN else "thin" if ratio >= STOP else "stop",
        }
        for role in PER_ERA_ROLES:
            template = ws.path(f"prereg/prompts/{role}.md")
            if template.exists():
                need = invoke.estimate_tokens(template.read_text() + body)
                for lineage, lcfg in cfg["lineages"].items():
                    if need + lcfg["reserve_output_tokens"] > lcfg["input_budget_tokens"]:
                        raise UsageError(f"era {era['id']} is too large for {role} on {lineage}")
    store.write_json(ws.path("prepare/stats.json"), stats)
    return {"status": "done", "stats": stats}
