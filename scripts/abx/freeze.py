"""`freeze`: re-qualify if a CLI changed, then pre-register method, substrate and seal as generation A.

Generation A also freezes the inputs later figures depend on: preparation statistics, the
IPIP instrument copy, the qualification snapshot, and the zoning calls' records.
"""

import shutil

from . import config, invoke, ipip, lifecycle, qualify, store
from .errors import IntegrityError, UsageError

__all__ = ["QUALIFICATION_A", "freeze"]

QUALIFICATION_A = "prereg/qualification-A.json"
GEN_A_FILES = ("config.json", lifecycle.HASHES, ipip.FROZEN_COPY, QUALIFICATION_A, "prepare/redacted.txt",
               "prepare/segments.json", "prepare/sentences.json", "prepare/eras.json", "prepare/redactions.json",
               "prepare/stats.json")
GEN_A_GLOBS = ("prereg/prompts/*.md", "prereg/schemas/*.json", "prepare/substrate/*.md", "prepare/chunks/*.txt",
               "prepare/zoning/*.json", "run/calls/prepare/**/*.json")


def freeze(ws: store.Workspace) -> dict:
    lifecycle.enter(ws, "freeze")
    if not ws.path("prepare/stats.json").exists():
        raise UsageError("run `prepare` to the end first")
    cfg = config.load(ws)
    requalified = False
    try:
        for lineage in cfg.lineages:
            invoke.check_fingerprint(cfg, lineage, invoke.qualified(ws)[lineage])
    except IntegrityError:
        qualify.qualify(ws, cfg)
        requalified = True
    shutil.copy(ws.path(invoke.QUALIFICATION), ws.path(QUALIFICATION_A))
    paths = [*GEN_A_FILES, *(ws.rel(p) for g in GEN_A_GLOBS for p in sorted(ws.root.glob(g)))]
    entry = store.append_generation(ws, "A", paths)
    return {"generation": "A", "artifacts": len(entry["artifacts"]), "requalified": requalified}
