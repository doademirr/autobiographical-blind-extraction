"""Artifact ids: a typed grammar, and where each artifact lives in a workspace.

An id is `kind:part:…`. Every part is checked against its kind's grammar and arity, so an
id can only name a file inside its kind's directory; every prompt input is one of these files.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from . import store
from .errors import UsageError

__all__ = ["ERA_ID", "Ref", "parse", "path_of", "resolver"]

ERA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
_PART = {
    "role": re.compile(r"^[a-z_]{1,32}$"),
    "name": re.compile(r"^[a-z_]{1,32}$"),
    "lineage": re.compile(r"^[a-z]{1,16}$"),
    "run": re.compile(r"^[1-9][0-9]?$"),
    "era": ERA_ID,
    "era_or_all": re.compile(r"^(all|[A-Za-z0-9][A-Za-z0-9_-]{0,31})$"),
}
# kind -> (part grammar, file pattern relative to the workspace)
_KINDS: dict[str, tuple[tuple[str, ...], str]] = {
    "template": (("role",), "prereg/prompts/{0}.md"),
    "schema": (("name",), "prereg/schemas/{0}.json"),
    "chunk": (("era",), "prepare/chunks/{0}.txt"),
    "era": (("era",), "prepare/substrate/{0}.md"),
    "discovery": (("lineage", "run", "era"), "run/discovery/{0}-r{1}-{2}.json"),
    "hypotheses": (("lineage", "run", "era"), "run/discovery/{0}-r{1}-{2}.hypotheses.md"),
    "pool": (("=all",), "run/discovery/pool.md"),
    "card": (("=B",), "run/codebook/card.md"),
    "ledger": (("lineage", "run", "era_or_all"), "run/deductive/ledger-{0}-r{1}-{2}.json"),
    "constructs": (("=all",), "run/crosswalk/constructs.md"),
    "self_prediction": (("=sealed",), "sealed/self-prediction.md"),
}


@dataclass(frozen=True)
class Ref:
    kind: str
    parts: tuple[str, ...]

    def __str__(self) -> str:
        return ":".join((self.kind, *self.parts))

    @property
    def lineage(self) -> str | None:
        return self.parts[0] if self.kind in {"discovery", "hypotheses", "ledger"} else None

    @property
    def run(self) -> int | None:
        return int(self.parts[1]) if self.kind in {"discovery", "hypotheses", "ledger"} else None

    @property
    def era(self) -> str | None:
        if self.kind in {"chunk", "era"}:
            return self.parts[0]
        if self.kind in {"discovery", "hypotheses", "ledger"}:
            return self.parts[2]
        return None


def parse(artifact_id: str) -> Ref:
    kind, *parts = artifact_id.split(":")
    if kind not in _KINDS:
        raise UsageError(f"unknown artifact kind in {artifact_id!r}")
    grammar = _KINDS[kind][0]
    if len(parts) != len(grammar):
        raise UsageError(f"artifact id {artifact_id!r} needs {len(grammar)} part(s)")
    for part, rule in zip(parts, grammar, strict=True):
        ok = part == rule[1:] if rule.startswith("=") else bool(_PART[rule].match(part))
        if not ok:
            raise UsageError(f"artifact id {artifact_id!r}: bad {rule.lstrip('=')} part {part!r}")
    return Ref(kind, tuple(parts))


def path_of(ws: store.Workspace, artifact_id: str) -> Path:
    ref = parse(artifact_id)
    path = ws.path(_KINDS[ref.kind][1].format(*ref.parts))
    if not path.resolve().is_relative_to(ws.root.resolve()):
        raise UsageError(f"artifact id {artifact_id!r} resolves outside the workspace")
    return path


def resolver(ws: store.Workspace):
    def resolve(artifact_id: str) -> str:
        path = path_of(ws, artifact_id)
        if not path.exists():
            raise UsageError(f"artifact {artifact_id} is missing ({ws.rel(path)})")
        return path.read_text(encoding="utf-8")
    return resolve
