"""The stage-entry guard every command passes before it writes anything or calls a model.

It verifies the frozen state (manifest chain, frozen files, sealed hashes once sealed) and
refuses a stage the lifecycle has closed: nothing before generation A can be redone after it,
and a workspace is unmasked once.
"""

from collections.abc import Callable
from typing import NamedTuple

from . import store
from .errors import IntegrityError, UsageError

__all__ = ["HASHES", "SEALED", "Arg", "CliResult", "Preflight", "Stage", "enter", "returns", "verify_sealed"]


class Preflight(NamedTuple):
    """What a model-calling stage will spend, shown before it runs."""

    model_calls: int
    conditional_calls: int
    note: str


class Arg(NamedTuple):
    flags: tuple[str, ...]
    options: dict


class CliResult(NamedTuple):
    """What a command hands the CLI: the summary to show (a `next` value is a code the CLI renders) and the exit
    code. The stage decides both; the CLI only prints."""

    summary: dict
    exit_code: int = 0


def returns(stage_fn: Callable) -> Callable:
    """The `run` of a workspace stage whose summary is what it returns and which always exits 0."""
    def run(ws, args) -> CliResult:
        return CliResult(stage_fn(ws))
    return run


class Stage(NamedTuple):
    """A command, declared by the module that implements it; `run.py` discovers and dispatches these.

    Every `run` takes the target (the workspace, or for a stage that `creates_workspace`, its path) and the parsed
    arguments, and returns a `CliResult`. `needs`, `closed_after` and `verifies_seal` are its lifecycle rules.
    """

    name: str
    order: int
    help: str
    run: Callable
    estimate: Callable | None = None
    args: tuple[Arg, ...] = ()
    needs: str | None = None
    closed_after: str | None = None
    verifies_seal: bool = True
    creates_workspace: bool = False
    checks_method: bool = False  # refuses a workspace made under an older method, before even its estimate

SEALED = ("sealed/self-prediction.md", "sealed/ipip-120.csv")
HASHES = "prereg/sealed-hashes.json"

def enter(ws: store.Workspace, stage: "Stage") -> set[str]:
    """Check integrity and the stage's own lifecycle rules before it writes or calls anything."""
    store.verify_manifest(ws)
    gens = store.frozen_generations(ws)
    if stage.verifies_seal:
        verify_sealed(ws)
    if stage.closed_after and stage.closed_after in gens:
        raise UsageError(f"`{stage.name}` is closed: generation {stage.closed_after} is frozen; "
                         "a new run needs a new workspace")
    if stage.needs and stage.needs not in gens:
        raise UsageError(f"`{stage.name}` needs generation {stage.needs}; run the earlier stages first")
    return gens


def verify_sealed(ws: store.Workspace) -> None:
    if not ws.path(HASHES).exists():
        raise UsageError("sealed files are not sealed yet; run `seal`")
    for rel, digest in store.read_json(ws.path(HASHES)).items():
        if not ws.path(rel).exists() or store.sha256_file(ws.path(rel)) != digest:
            raise IntegrityError(f"{rel} changed after sealing")
