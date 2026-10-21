"""Artifact ids: a typed grammar, and where each artifact lives in a workspace.

An id is `kind:part:…`. Every part is checked against its kind's grammar and arity, and the
file it names must sit at exactly that path inside the kind's directory, with no symlink on
the way; every prompt input is one of these files.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from . import store
from .errors import UsageError

__all__ = ["ERA_ID", "Ref", "directory", "parse", "path_of", "resolver"]

ERA_ID = re.compile(r"(?!all\Z)[A-Za-z0-9][A-Za-z0-9_-]{0,31}")
_PART = {
    "role": re.compile(r"[a-z_]{1,32}"),
    "name": re.compile(r"[a-z_]{1,32}"),
    "lineage": re.compile(r"[a-z]{1,16}"),
    "run": re.compile(r"[1-9][0-9]?"),
    "part": re.compile(r"[1-9][0-9]{0,3}"),
    "era": ERA_ID,
}
# kind -> (named parts, file pattern relative to the workspace)
_KINDS: dict[str, tuple[tuple[str, ...], str]] = {
    "template": (("role",), "prereg/prompts/{role}.md"),
    "schema": (("name",), "prereg/schemas/{name}.json"),
    "facets": (("=all",), "prereg/facets.md"),
    "chunk": (("era", "part"), "prepare/chunks/{era}/{part}.txt"),
    "era": (("era",), "prepare/substrate/{era}.md"),
    "excerpt": (("era", "part"), "prepare/calibration/{era}/{part}.txt"),
    "foils": (("era",), "prereg/foils/{era}.md"),
    "discovery": (("lineage", "run", "era"), "run/discovery/{lineage}-r{run}-{era}.json"),
    "hypotheses": (("lineage", "run", "era"), "run/discovery/{lineage}-r{run}-{era}.hypotheses.md"),
    "pool": (("=all",), "run/discovery/pool.md"),
    "codebook": (("=B",), "run/codebook/codebook.md"),
    "card": (("=B",), "run/codebook/card.md"),
    "ledger": (("lineage", "run", "era"), "run/deductive/ledger-{lineage}-r{run}-{era}.json"),
    "ledgers": (("lineage", "run"), "run/deductive/ledgers-{lineage}-r{run}.json"),
    "constructs": (("=all",), "run/crosswalk/constructs.md"),
    "self_prediction": (("=sealed",), "sealed/self-prediction.md"),
}


@dataclass(frozen=True)
class Ref:
    """A parsed artifact id with named parts; absent parts are None."""

    kind: str
    role: str | None = None
    name: str | None = None
    lineage: str | None = None
    run: int | None = None
    era: str | None = None
    part: int | None = None
    literal: str | None = None

    def __str__(self) -> str:
        fields = _KINDS[self.kind][0]
        return ":".join([self.kind, *(self.literal if f.startswith("=") else str(getattr(self, f))
                                      for f in fields)])


def parse(artifact_id: str) -> Ref:
    kind, *parts = artifact_id.split(":")
    if kind not in _KINDS:
        raise UsageError("unknown artifact kind")
    fields = _KINDS[kind][0]
    if len(parts) != len(fields):
        raise UsageError(f"{kind} artifact id needs {len(fields)} part(s)")
    named: dict = {}
    for part, field in zip(parts, fields, strict=True):
        if field.startswith("="):
            if part != field[1:]:
                raise UsageError(f"{kind} artifact id must end in {field[1:]!r}")
            named["literal"] = part
        elif not _PART[field].fullmatch(part):
            raise UsageError(f"{kind} artifact id has a malformed {field}")
        else:
            named[field] = int(part) if field in {"run", "part"} else part
    return Ref(kind, **named)


def directory(kind: str) -> str:
    """The workspace directory every artifact of `kind` lives under (the fixed part of its file pattern)."""
    return _KINDS[kind][1].split("{")[0].rstrip("/")


def path_of(ws: store.Workspace, artifact_id: str) -> Path:
    ref = parse(artifact_id)
    pattern = _KINDS[ref.kind][1]
    rel = pattern.format(**{f: getattr(ref, f) for f in ("role", "name", "lineage", "run", "era", "part")})
    path = ws.path(rel)
    root = ws.root.resolve()
    if path.exists() and path.resolve() != root / rel:
        raise UsageError(f"artifact {ref.kind} resolves through a link; refusing it")
    return path


def resolver(ws: store.Workspace):
    def resolve(artifact_id: str) -> str:
        path = path_of(ws, artifact_id)
        if not path.exists():
            raise UsageError(f"artifact {artifact_id} is missing ({ws.rel(path)})")
        return path.read_text(encoding="utf-8")
    return resolve
