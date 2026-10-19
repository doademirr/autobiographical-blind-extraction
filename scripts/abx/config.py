"""`config.json`, parsed once at the boundary into typed records. Malformed config is a usage error."""

from dataclasses import dataclass, field

from . import store
from .errors import UsageError

__all__ = ["Config", "Lineage", "load", "parse"]

LINEAGES = ("claude", "codex")


@dataclass(frozen=True)
class Lineage:
    name: str
    cli: str
    model: str
    input_budget_tokens: int
    reserve_output_tokens: int
    raw: dict = field(compare=False, repr=False)       # hashed into the fingerprint as written
    locked_read_result: str = ""                      # claude: the pinned refusal of a scripted Read
    sandbox_exec: str = ""                            # codex only, from here down
    sandbox_allow: tuple[str, ...] = ()
    auth_file: str = ""
    disable: tuple[str, ...] = ()
    config: tuple[str, ...] = ()
    retained_tools: dict = field(default_factory=dict)
    capture_forward: bool = False


@dataclass(frozen=True)
class Config:
    lineages: dict[str, Lineage]
    runs: int
    zoner: str
    codebook_author: str
    crosswalk_coders: tuple[str, ...]
    canaries: tuple[str, ...]
    env_passthrough: tuple[str, ...]
    timeout_s: int

    def lineage(self, name: str) -> Lineage:
        return self.lineages[name]


def _get(obj: dict, key: str, kind, where: str):
    if not isinstance(obj, dict) or key not in obj:
        raise UsageError(f"config.json: {where} is missing {key!r}")
    value = obj[key]
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise UsageError(f"config.json: {where}.{key} must be {getattr(kind, '__name__', kind)}")
    return value


def _strings(obj: dict, key: str, where: str) -> tuple[str, ...]:
    values = _get(obj, key, list, where)
    if not all(isinstance(v, str) for v in values):
        raise UsageError(f"config.json: {where}.{key} must be a list of strings")
    return tuple(values)


def _lineage(name: str, obj: dict) -> Lineage:
    where = f"lineages.{name}"
    common = {"name": name, "raw": obj, "cli": _get(obj, "cli", str, where), "model": _get(obj, "model", str, where),
              "input_budget_tokens": _get(obj, "input_budget_tokens", int, where),
              "reserve_output_tokens": _get(obj, "reserve_output_tokens", int, where)}
    if name == "claude":
        return Lineage(**common, locked_read_result=_get(obj, "locked_read_result", str, where))
    retained = _get(obj, "retained_tools", dict, where)
    for tool, spec in retained.items():
        well_formed = (isinstance(spec, dict) and isinstance(spec.get("call"), dict)
                       and isinstance(spec.get("result"), str))
        if not well_formed:
            raise UsageError(f"config.json: {where}.retained_tools.{tool} needs a call object and a result string")
    return Lineage(**common, sandbox_exec=_get(obj, "sandbox_exec", str, where),
                   sandbox_allow=_strings(obj, "sandbox_allow", where), auth_file=_get(obj, "auth_file", str, where),
                   disable=_strings(obj, "disable", where), config=_strings(obj, "config", where),
                   retained_tools=retained, capture_forward=_get(obj, "capture_forward", bool, where))


def parse(obj: dict) -> Config:
    lineages = _get(obj, "lineages", dict, "config")
    if sorted(lineages) != sorted(LINEAGES):
        raise UsageError(f"config.json: lineages must be exactly {list(LINEAGES)}")
    roles = _get(obj, "roles", dict, "config")
    cfg = Config(
        lineages={n: _lineage(n, lineages[n]) for n in LINEAGES}, runs=_get(obj, "runs", int, "config"),
        zoner=_get(roles, "zoner", str, "roles"), codebook_author=_get(roles, "codebook_author", str, "roles"),
        crosswalk_coders=_strings(roles, "crosswalk_coders", "roles"), canaries=_strings(obj, "canaries", "config"),
        env_passthrough=_strings(obj, "env_passthrough", "config"), timeout_s=_get(obj, "timeout_s", int, "config"))
    for who in (cfg.zoner, cfg.codebook_author, *cfg.crosswalk_coders):
        if who not in LINEAGES:
            raise UsageError(f"config.json: roles name an unknown lineage {who!r}")
    if not 2 <= cfg.runs <= 9:
        raise UsageError("config.json: runs must be between 2 and 9")
    return cfg


def load(ws: store.Workspace) -> Config:
    return parse(store.read_json(ws.path("config.json")))
