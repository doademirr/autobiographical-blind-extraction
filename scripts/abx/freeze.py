"""`freeze`: refuse a zoner that failed calibration, re-qualify if a CLI changed, author the foils, then pre-register
method, substrate, foils and seal as generation A.

Generation A also freezes the inputs later figures depend on: preparation statistics, the
IPIP instrument copy, the qualification snapshot, the zoning calibration and its excerpts, and the zoning,
calibration-judge and foil-author calls' records.
"""

import shutil

from . import calibration, config, evidence, foils, invoke, ipip, lifecycle, prepare, qualify, store
from .errors import IntegrityError, UsageError

__all__ = ["STAGE", "estimate", "freeze"]

GEN_A_FILES = ("config.json", lifecycle.HASHES, ipip.FROZEN_COPY, invoke.QUALIFICATION_A, "prereg/facets.md",
               "prepare/redacted.txt", "prepare/offsets.json", "prepare/removed-sentences.json",
               "prepare/segments.json", "prepare/sentences.json", "prepare/eras.json", "prepare/redactions.json",
               "prepare/stats.json", "prepare/receipt.json", calibration.PATH)
GEN_A_GLOBS = ("prereg/prompts/*.md", "prereg/schemas/*.json", "prepare/substrate/*.md", "prepare/chunks/*/*.txt",
               f"{calibration.EXCERPTS}/*/*.txt",
               "prepare/zoning/*.json", "run/calls/prepare/**/*.json", "prereg/foils/*.json", "prereg/foils/*.md",
               "run/calls/freeze/**/*.json")


def estimate(ws: store.Workspace) -> lifecycle.Preflight:
    eras = len(store.read_json(ws.path("prepare/eras.json"))["eras"])
    return lifecycle.Preflight(eras, 2, "one foil-author call per era; re-qualification (one leak probe per "
                                        "lineage) only if a CLI changed since `prepare`")


def _check_inputs(ws: store.Workspace) -> None:
    stale = prepare.receipt_problems(ws)
    if stale:
        raise UsageError(f"preparation is not current ({', '.join(stale[:3])}); rerun `prepare`")
    lifecycle.verify_sealed(ws)


def freeze(ws: store.Workspace) -> dict:
    lifecycle.enter(ws, STAGE)
    invoke.check_method(ws)  # before the receipt: an older workspace's receipt lists files the current layout lacks
    _check_inputs(ws)
    calibration.check(ws)
    cfg = config.load(ws)
    requalified = False
    try:
        for lineage in cfg.lineages:
            invoke.check_fingerprint(cfg, lineage, invoke.qualified(ws)[lineage])
    except IntegrityError:
        qualify.qualify(ws, cfg)
        requalified = True
    shutil.copy(ws.path(invoke.QUALIFICATION), ws.path(invoke.QUALIFICATION_A))
    foils.author(ws, cfg, evidence.load(ws), store.sha256_file(ws.path("prepare/redacted.txt")))
    _check_inputs(ws)  # authoring takes a while; an input changed meanwhile must not be frozen under these foils
    paths = [*GEN_A_FILES, *(ws.rel(p) for g in GEN_A_GLOBS for p in sorted(ws.root.glob(g)))]
    entry = store.append_generation(ws, "A", paths)
    return {"generation": "A", "artifacts": len(entry["artifacts"]), "requalified": requalified}


STAGE = lifecycle.Stage("freeze", 3, "pre-register generation A", freeze, estimate, closed_after="A",
                        checks_method=True)
