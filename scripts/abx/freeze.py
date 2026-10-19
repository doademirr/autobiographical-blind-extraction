"""`freeze`: re-qualify if a CLI changed, then pre-register method, substrate and seal as generation A."""

from . import invoke, qualify, seal, store
from .errors import IntegrityError, UsageError

GEN_A_GLOBS = ("prereg/prompts/*.md", "prereg/schemas/*.json", "prepare/substrate/*.md", "prepare/chunks/*.txt",
               "prepare/zoning/*.json")
GEN_A_FILES = ("config.json", seal.HASHES, "prepare/redacted.txt", "prepare/segments.json", "prepare/sentences.json",
               "prepare/eras.json", "prepare/redactions.json")


def freeze(ws: store.Workspace) -> dict:
    if "A" in store.frozen_generations(ws):
        raise UsageError("generation A is already frozen")
    if not ws.path("prepare/stats.json").exists():
        raise UsageError("run `prepare` first")
    seal.verify_sealed(ws)
    cfg = store.read_json(ws.path("config.json"))
    qual = qualify.qualified(ws)
    try:
        for lineage in cfg["lineages"]:
            invoke.check_fingerprint(cfg, lineage, qual[lineage])
        requalified = False
    except IntegrityError:
        qualify.qualify(ws, cfg)
        requalified = True
    paths = [*GEN_A_FILES, *(ws.rel(p) for g in GEN_A_GLOBS for p in sorted(ws.root.glob(g)))]
    entry = store.append_generation(ws, "A", paths)
    return {"generation": "A", "artifacts": len(entry["artifacts"]), "requalified": requalified}
