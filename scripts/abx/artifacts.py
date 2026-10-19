"""Where each artifact id lives in a workspace. Every prompt input is one of these files."""

from pathlib import Path

from . import store
from .errors import UsageError

_LAYOUT = {
    "template": "prereg/prompts/{0}.md",
    "schema": "prereg/schemas/{0}.json",
    "chunk": "prepare/chunks/{0}.txt",
    "era": "prepare/substrate/{0}.md",
    "discovery": "run/discovery/{0}-r{1}-{2}.json",
    "hypotheses": "run/discovery/{0}-r{1}-{2}.hypotheses.md",
    "pool": "run/discovery/pool.md",
    "card": "run/codebook/card.md",
    "ledger": "run/deductive/ledger-{0}-r{1}-{2}.json",
    "constructs": "run/crosswalk/constructs.md",
    "self_prediction": "sealed/self-prediction.md",
}


def path_of(ws: store.Workspace, artifact_id: str) -> Path:
    kind, *parts = artifact_id.split(":")
    if kind not in _LAYOUT:
        raise UsageError(f"unknown artifact kind in {artifact_id!r}")
    return ws.path(_LAYOUT[kind].format(*parts))


def resolver(ws: store.Workspace):
    def resolve(artifact_id: str) -> str:
        path = path_of(ws, artifact_id)
        if not path.exists():
            raise UsageError(f"artifact {artifact_id} is missing ({ws.rel(path)})")
        return path.read_text(encoding="utf-8")
    return resolve
