"""Workspace layout, strict JSON, hashing and the manifest hash chain."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import IntegrityError, UsageError

MANIFEST = "prereg/manifest.jsonl"


@dataclass(frozen=True)
class Workspace:
    root: Path

    def path(self, rel: str) -> Path:
        return self.root / rel

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical(obj) -> str:
    """The one serialisation hashed anywhere: key order and whitespace never move a hash."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _reject_constant(name):
    raise ValueError(f"non-finite number {name} is not valid JSON")


def _no_duplicate_keys(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate key in JSON object: {min(k for k in keys if keys.count(k) > 1)}")
    return dict(pairs)


def loads_strict(text: str):
    """JSON that refuses NaN/Infinity and duplicate keys, which `json.loads` silently accepts."""
    try:
        return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_no_duplicate_keys)
    except RecursionError as exc:
        raise ValueError("JSON nested too deeply") from exc


def read_json(path: Path):
    try:
        return loads_strict(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except ValueError as exc:
        raise UsageError(f"{path}: invalid JSON ({exc})") from exc


def write_text_atomic(path: Path, text: str) -> None:
    """Readers see the old file or the new one, never a partial write, even if killed mid-write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path: Path, obj) -> None:
    write_text_atomic(path, json.dumps(obj, indent=1, ensure_ascii=False, allow_nan=False) + "\n")


def read_manifest(ws: Workspace) -> list[dict]:
    path = ws.path(MANIFEST)
    if not path.exists():
        return []
    try:
        entries = [loads_strict(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except ValueError as exc:
        raise IntegrityError(f"manifest is unreadable: {exc}") from exc
    if not all(isinstance(e, dict) and isinstance(e.get("artifacts"), dict) and "gen" in e for e in entries):
        raise IntegrityError("manifest entries are malformed")
    return entries


def _entry_hash(entry: dict) -> str:
    return sha256_text(canonical({k: v for k, v in entry.items() if k != "hash"}))


def append_generation(ws: Workspace, gen: str, rel_paths: list[str]) -> dict:
    """Freeze the named files as generation `gen`, chained to the previous entry."""
    entries = read_manifest(ws)
    if any(e["gen"] == gen for e in entries):
        raise IntegrityError(f"generation {gen} is already frozen")
    entry = {
        "gen": gen,
        "artifacts": {rel: sha256_file(ws.path(rel)) for rel in sorted(rel_paths)},
        "prev": entries[-1]["hash"] if entries else None,
    }
    entry["hash"] = _entry_hash(entry)
    lines = [canonical(e) for e in [*entries, entry]]
    write_text_atomic(ws.path(MANIFEST), "\n".join(lines) + "\n")
    return entry


def verify_manifest(ws: Workspace) -> list[dict]:
    """Check the chain and every frozen file; any difference is an unauthorised edit."""
    entries = read_manifest(ws)
    prev = None
    for entry in entries:
        if entry.get("prev") != prev or entry.get("hash") != _entry_hash(entry):
            raise IntegrityError(f"manifest chain broken at generation {entry.get('gen')}")
        for rel, digest in entry["artifacts"].items():
            path = ws.path(rel)
            if not path.exists():
                raise IntegrityError(f"frozen file missing: {rel} (generation {entry['gen']})")
            if sha256_file(path) != digest:
                raise IntegrityError(f"frozen file changed: {rel} (generation {entry['gen']})")
        prev = entry["hash"]
    return entries


def frozen_generations(ws: Workspace) -> set[str]:
    return {e["gen"] for e in read_manifest(ws)}
