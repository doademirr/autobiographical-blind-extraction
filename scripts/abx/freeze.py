"""`freeze`: re-qualify if a CLI changed, then pre-register method, substrate and seal as generation A.

Generation A also freezes the inputs later figures depend on: preparation statistics, the
IPIP instrument copy, the qualification snapshot, and the zoning calls' records.
"""

import shutil

from . import config, invoke, ipip, lifecycle, prepare, qualify, store
from .errors import IntegrityError, UsageError

__all__ = ["STAGE", "estimate", "freeze"]

GEN_A_FILES = ("config.json", lifecycle.HASHES, ipip.FROZEN_COPY, invoke.QUALIFICATION_A, "prereg/facets.md",
               "prepare/redacted.txt", "prepare/offsets.json", "prepare/removed-sentences.json",
               "prepare/segments.json", "prepare/sentences.json", "prepare/eras.json", "prepare/redactions.json",
               "prepare/stats.json", "prepare/receipt.json")
GEN_A_GLOBS = ("prereg/prompts/*.md", "prereg/schemas/*.json", "prepare/substrate/*.md", "prepare/chunks/*.txt",
               "prepare/zoning/*.json", "run/calls/prepare/**/*.json")


def estimate(ws: store.Workspace) -> lifecycle.Preflight:
    return lifecycle.Preflight(0, 2, "re-qualification (one leak probe per lineage) only if a CLI changed since "
                                     "`prepare`")


def freeze(ws: store.Workspace) -> dict:
    lifecycle.enter(ws, STAGE)
    stale = prepare.receipt_problems(ws)
    if stale:
        raise UsageError(f"preparation is not current ({', '.join(stale[:3])}); rerun `prepare`")
    cfg = config.load(ws)
    invoke.check_method(ws)
    requalified = False
    try:
        for lineage in cfg.lineages:
            invoke.check_fingerprint(cfg, lineage, invoke.qualified(ws)[lineage])
    except IntegrityError:
        qualify.qualify(ws, cfg)
        requalified = True
    shutil.copy(ws.path(invoke.QUALIFICATION), ws.path(invoke.QUALIFICATION_A))
    paths = [*GEN_A_FILES, *(ws.rel(p) for g in GEN_A_GLOBS for p in sorted(ws.root.glob(g)))]
    entry = store.append_generation(ws, "A", paths)
    return {"generation": "A", "artifacts": len(entry["artifacts"]), "requalified": requalified}


STAGE = lifecycle.Stage("freeze", 3, "pre-register generation A", freeze, estimate, closed_after="A")
