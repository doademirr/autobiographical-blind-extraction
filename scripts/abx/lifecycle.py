"""The stage-entry guard every command passes before it writes anything or calls a model.

It verifies the frozen state (manifest chain, frozen files, sealed hashes once sealed) and
refuses a stage the lifecycle has closed: nothing before generation A can be redone after it,
and a workspace is unmasked once.
"""

from collections.abc import Callable
from typing import NamedTuple

from . import store
from .errors import IntegrityError, UsageError

__all__ = ["HASHES", "SEALED", "Preflight", "Stage", "enter", "verify_sealed"]


class Preflight(NamedTuple):
    """What a model-calling stage will spend, shown before it runs."""

    model_calls: int
    conditional_calls: int
    note: str


class Stage(NamedTuple):
    """A workspace command, declared by the module that implements it; `run.py` discovers these."""

    name: str
    order: int
    help: str
    run: Callable
    estimate: Callable | None = None

SEALED = ("sealed/self-prediction.md", "sealed/ipip-120.csv")
HASHES = "prereg/sealed-hashes.json"

_BEFORE_A = {"prepare", "seal", "freeze"}
_NEEDS = {"extract": "A", "unmask": "C"}


def enter(ws: store.Workspace, stage: str) -> set[str]:
    """Check integrity and stage order; returns the frozen generations."""
    store.verify_manifest(ws)
    gens = store.frozen_generations(ws)
    if stage not in _BEFORE_A - {"freeze"}:
        verify_sealed(ws)
    if stage in _BEFORE_A and "A" in gens:
        raise UsageError(f"`{stage}` is closed: generation A is frozen; a new run needs a new workspace")
    if stage in _NEEDS and "E" in gens:
        raise UsageError("this workspace is unmasked; a new run needs a new workspace")
    if stage in _NEEDS and _NEEDS[stage] not in gens:
        raise UsageError(f"`{stage}` needs generation {_NEEDS[stage]}; run the earlier stages first")
    return gens


def verify_sealed(ws: store.Workspace) -> None:
    if not ws.path(HASHES).exists():
        raise UsageError("sealed files are not sealed yet; run `seal`")
    for rel, digest in store.read_json(ws.path(HASHES)).items():
        if not ws.path(rel).exists() or store.sha256_file(ws.path(rel)) != digest:
            raise IntegrityError(f"{rel} changed after sealing")
