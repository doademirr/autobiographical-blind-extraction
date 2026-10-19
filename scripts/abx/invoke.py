"""The only module that starts a model CLI, and the single boundary every model call passes.

`call` takes a `CallRequest` (artifact ids, never text), assembles and audits the prompt,
checks fingerprint and budget, runs one isolated process (`execute`), audits its event
stream, validates the output and records it, or reuses a record whose every input still
matches. Each process starts in an empty temp directory (also its cwd: Codex reads its
launch directory); Codex runs with a temp CODEX_HOME inside an OS read sandbox.
"""

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import artifacts, prompts, store, withheld
from . import schema as jsonschema
from .config import Config, Lineage
from .errors import CallFailed, IntegrityError, IsolationError, UsageError
from .roles import role as get_role

__all__ = ["CallRequest", "Event", "Result", "audit_events", "call", "check_fingerprint", "claude_argv",
           "codex_argv", "estimate_tokens", "execute", "live_fingerprint", "parse_claude", "parse_codex",
           "record_path", "sandbox_profile"]

SYSTEM_READ_ROOTS = (
    "/System", "/usr/lib", "/usr/libexec", "/usr/bin", "/usr/sbin", "/usr/share", "/bin", "/sbin",
    "/Library/Apple", "/private/etc", "/private/var/db/dyld", "/dev", "/Library/Preferences/SystemConfiguration",
)
BASE_ENV_KEYS = ("PATH", "HOME", "LANG", "TMPDIR", "USER", "LOGNAME")
CLAUDE_TEXT_BLOCKS = {"text", "thinking", "redacted_thinking"}
CODEX_ITEMS = {"agent_message", "reasoning", "error"}
CODEX_LIFECYCLE = {"thread.started", "turn.started"}
CODEX_PLAIN_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\S+\s|Reading additional input from stdin)")
QUALIFICATION = "run/qualification.json"


def sandbox_profile(allow: list[str]) -> str:
    """Deny every file read except system runtime paths and the given (canonicalised) roots.

    The root directory itself must be readable or dyld aborts; metadata reads stay allowed so
    paths resolve. `/usr/local` is deliberately not a runtime root.
    """
    def subpaths(paths):
        return " ".join(f'(subpath "{os.path.realpath(p)}")' for p in paths)

    return (
        "(version 1)\n(allow default)\n(deny file-read*)\n(allow file-read-metadata)\n"
        f'(allow file-read* (literal "/") {subpaths(SYSTEM_READ_ROOTS)})\n'
        f"(allow file-read* {subpaths(allow)})\n"
    )


@dataclass(frozen=True)
class Event:
    """One event from a CLI stream, reduced to what the audit needs."""

    type: str
    detail: str = ""        # Claude: subtype or block types; Codex: the item type
    tools: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    registry_present: bool = True


@dataclass
class Result:
    status: str = "no_terminal"     # "success" | "failed" | "no_terminal"
    text: str | None = None
    model: str | None = None
    detail: str = ""
    events: list[Event] = field(default_factory=list)


def audit_events(lineage: str, events: list[Event], allowed: frozenset[str] = frozenset()) -> list[str]:
    """Tool events in a stream: every event kind outside the lineage's allowlist, plus `allowed` exceptions."""
    found = []
    for ev in events:
        kind = f"{ev.type}:{ev.detail}"
        if kind in allowed:
            continue
        if lineage == "claude":
            if ev.type == "system" and ev.detail == "init":
                if not ev.registry_present or ev.tools or ev.mcp_servers:
                    found.append(f"init-registry:{list(ev.tools)}:{list(ev.mcp_servers)}")
            elif ev.type == "assistant":
                found += [f"assistant-block:{b}" for b in ev.detail.split(",") if b and b not in CLAUDE_TEXT_BLOCKS]
            elif ev.type != "result":
                found.append(kind)
        elif ev.type in CODEX_LIFECYCLE or ev.type in {"error", "turn.completed", "turn.failed"}:
            continue
        elif ev.type in {"item.started", "item.updated", "item.completed"}:
            if ev.detail not in CODEX_ITEMS:
                found.append(kind)
        else:
            found.append(kind)
    return found


def parse_claude(lines: list[str]) -> Result:
    out = Result()
    for line in lines:
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            out.events.append(Event("unparseable"))
            continue
        if not isinstance(ev, dict):
            out.events.append(Event("unparseable"))
            continue
        etype, sub = str(ev.get("type")), ev.get("subtype")
        if etype == "system" and sub == "init":
            out.model = ev.get("model")
            out.events.append(Event("system", "init", tuple(map(str, ev.get("tools") or [])),
                                    tuple(map(str, ev.get("mcp_servers") or [])),
                                    registry_present="tools" in ev and "mcp_servers" in ev))
        elif etype == "assistant":
            blocks = (ev.get("message") or {}).get("content") or []
            out.events.append(Event("assistant", ",".join(str(b.get("type")) for b in blocks if isinstance(b, dict))))
        elif etype == "result":
            out.events.append(Event("result", str(sub)))
            ok = sub == "success" and ev.get("is_error") is False
            out.status = "success" if ok else "failed"
            out.text = ev.get("result") if ok else None
            out.detail = "" if ok else f"result {sub}"
        else:
            out.events.append(Event(etype, str(sub or "")))
    return out


def parse_codex(lines: list[str]) -> Result:
    out = Result()
    for line in lines:
        stripped = line.strip()
        if not stripped or CODEX_PLAIN_LINE.match(stripped):
            continue
        try:
            ev = json.loads(stripped)
        except ValueError:
            if stripped[0] in "{[":
                out.events.append(Event("unparseable"))
            continue
        if not isinstance(ev, dict):
            out.events.append(Event("unparseable"))
            continue
        etype = str(ev.get("type"))
        item = ev.get("item") if isinstance(ev.get("item"), dict) else {}
        out.events.append(Event(etype, str(item.get("type", ""))))
        if etype == "item.completed" and item.get("type") == "agent_message":
            out.text = item.get("text")
        elif etype == "turn.completed":
            out.status = "success"
        elif etype == "turn.failed":
            out.status = "failed"
            out.detail = "turn failed"
    return out


def claude_argv(lin: Lineage, tools: str = "", extra: tuple[str, ...] = ()) -> list[str]:
    return [lin.cli, "-p", "--setting-sources", "", "--strict-mcp-config", "--tools", tools, *extra,
            "--no-session-persistence", "--output-format", "stream-json", "--verbose", "--model", lin.model]


def codex_argv(lin: Lineage, locked: bool = True) -> list[str]:
    """The pinned Codex argv; `locked=False` (qualification's positive controls only) drops sandbox and disables."""
    core = [lin.cli, "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "-s", "read-only",
            "--skip-git-repo-check", "--cd", "<cwd>", "-m", lin.model]
    if not locked:
        return [*core, "-"]
    flags = [x for f in lin.disable for x in ("--disable", f)] + [x for c in lin.config for x in ("-c", c)]
    return [lin.sandbox_exec, "-f", "<profile>", *core, "--output-schema", "<schema>", *flags, "-"]


def _pinned_argv(lin: Lineage) -> list[str]:
    return claude_argv(lin) if lin.name == "claude" else codex_argv(lin)


def cli_version(cli: str) -> str:
    try:
        p = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UsageError(f"cannot run {cli} --version: {exc}") from exc
    if p.returncode != 0:
        raise UsageError(f"{cli} --version exited {p.returncode}")
    return p.stdout.strip()


def live_fingerprint(cfg: Config, lineage: str) -> dict:
    lin = cfg.lineage(lineage)
    return {
        "cli": lin.cli,
        "cli_version": cli_version(lin.cli),
        "invocation_hash": store.sha256_text(store.canonical(_pinned_argv(lin))),
        "config_hash": store.sha256_text(store.canonical(lin.raw)),
    }


def qualified(ws: store.Workspace) -> dict:
    path = ws.path(QUALIFICATION)
    if not path.exists():
        raise UsageError("no qualification on record; run `prepare` first")
    return store.read_json(path)


def check_fingerprint(cfg: Config, lineage: str, qualified_fp: dict) -> dict:
    live = live_fingerprint(cfg, lineage)
    changed = [k for k, v in live.items() if qualified_fp.get(k) != v]
    if changed:
        raise IntegrityError(f"{lineage} fingerprint changed since qualification: {', '.join(changed)}")
    return {**live, "resolved_model": qualified_fp.get("resolved_model")}


def _env(cfg: Config, extra: dict[str, str]) -> dict[str, str]:
    keys = (*BASE_ENV_KEYS, *cfg.env_passthrough)
    return {**{k: os.environ[k] for k in keys if k in os.environ}, **extra}


def _run(argv: list[str], prompt: str, cwd: Path, env: dict[str, str], timeout: int) -> tuple[int | None, list[str]]:
    """(exit code, stdout lines); exit code None on a timeout, with whatever stdout arrived."""
    try:
        p = subprocess.run(argv, input=prompt, capture_output=True, text=True, cwd=cwd, env=env, timeout=timeout,
                           check=False)
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return None, partial.splitlines()
    except OSError as exc:
        raise CallFailed(f"CLI could not start: {exc}") from exc
    return p.returncode, p.stdout.splitlines()


def execute(cfg: Config, lineage: str, prompt_text: str, schema: str | None, argv: list[str] | None = None,
            extra_args: list[str] | None = None, env_extra: dict[str, str] | None = None) -> tuple[int | None, Result]:
    """One isolated CLI process; returns its exit code (None on timeout) and parsed stream.

    Qualification alone passes `argv` (an unlocked variant) or `extra_args` (provider overrides,
    inserted before Codex's trailing stdin marker); model calls always use the pinned argv.
    """
    lin = cfg.lineage(lineage)
    argv = list(argv or _pinned_argv(lin))
    if extra_args:
        argv = [*argv[:-1], *extra_args, argv[-1]] if argv[-1] == "-" else [*argv, *extra_args]
    tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="abx-")))
    try:
        cwd = tmp / "cwd"
        cwd.mkdir()
        env = _env(cfg, env_extra or {})
        if lineage == "claude":
            code, lines = _run(argv, prompt_text, cwd, env, cfg.timeout_s)
            return code, parse_claude(lines)
        home = tmp / "home"
        home.mkdir()
        shutil.copy(os.path.expanduser(lin.auth_file), home / "auth.json")
        (tmp / "profile.sb").write_text(sandbox_profile([*lin.sandbox_allow, str(tmp)]))
        (tmp / "schema.json").write_text(schema or "{}")
        argv = [{"<profile>": str(tmp / "profile.sb"), "<cwd>": str(cwd),
                 "<schema>": str(tmp / "schema.json")}.get(a, a) for a in argv]
        code, lines = _run(argv, prompt_text, cwd, {**env, "CODEX_HOME": str(home)}, cfg.timeout_s)
        return code, parse_codex(lines)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4 * 1.2)


@dataclass(frozen=True)
class CallRequest:
    """One model call, named by artifact ids. `call` turns it into a prompt; nothing else may."""

    stage: str
    role: str
    lineage: str
    run: int | None
    era: str | None
    generation: str
    slots: dict[str, str]
    params: dict[str, str] = field(default_factory=dict)
    validate: Callable[[object], list[str]] | None = None
    after_blind_results: bool = False

    @property
    def identity(self) -> str:
        return f"{self.stage}/{self.role}/{self.lineage}-r{self.run or 0}-{self.era or 'all'}"


def record_path(ws: store.Workspace, req: CallRequest) -> Path:
    return ws.path(f"run/calls/{req.identity}.json")


def _era_order(ws: store.Workspace) -> list[str]:
    path = ws.path("prepare/eras.json")
    return [e["id"] for e in store.read_json(path)["eras"]] if path.exists() else []


def parse_output(text: str | None, schema: dict, validate) -> tuple[object, list[str]]:
    if text is None:
        return None, ["no final message"]
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`").removeprefix("json").strip()
    try:
        out = store.loads_strict(body)
    except ValueError:
        return None, ["output is not JSON"]
    problems = jsonschema.errors(out, schema)
    if not problems and validate:
        problems = validate(out)
    return out, problems


def _incident(ws: store.Workspace, req: CallRequest, kind: str, detail: list[str]) -> None:
    store.write_json(ws.path(f"run/incidents/{req.identity}.json"),
                     {"identity": req.identity, "kind": kind, "detail": detail})


def _reusable(ws: store.Workspace, req: CallRequest, expect: dict, schema: dict) -> object:
    path = record_path(ws, req)
    if not path.exists():
        return None
    rec = store.read_json(path)
    if any(rec.get(k) != v for k, v in expect.items()):
        return None
    events = [Event(**e) for e in rec.get("events", [])]
    if audit_events(req.lineage, events):
        raise IsolationError(f"{req.identity}: its record holds a tool event; it cannot be reused")
    _, problems = parse_output(store.canonical(rec["output"]), schema, req.validate)
    return None if problems else rec["output"]


def call(ws: store.Workspace, cfg: Config, req: CallRequest) -> object:
    """Assemble, audit, run (or reuse) one model call and return its validated output."""
    rater = (req.lineage, req.run) if req.run is not None else None
    slots = {**req.slots, "schema": f"schema:{get_role(req.role).schema}"}
    prompt = prompts.assemble(req.role, slots, artifacts.resolver(ws), req.params, rater=rater, era=req.era,
                              era_order=_era_order(ws))
    prompts.audit(prompt, withheld.load(ws), after_blind_results=req.after_blind_results)
    fingerprint = check_fingerprint(cfg, req.lineage, qualified(ws)[req.lineage])
    lin = cfg.lineage(req.lineage)
    need = estimate_tokens(prompt.text) + lin.reserve_output_tokens
    if need > lin.input_budget_tokens:
        raise UsageError(f"{req.role} input for {req.lineage} needs ~{need} tokens, over the "
                         f"{lin.input_budget_tokens} budget")
    s_text = artifacts.resolver(ws)(slots["schema"])
    s_obj = store.loads_strict(s_text)
    expect = {"generation": req.generation, "fingerprint": fingerprint, "input_artifacts": prompt.artifacts,
              "schema_hash": store.sha256_text(s_text), "prompt_hash": store.sha256_text(prompt.text)}
    reused = _reusable(ws, req, expect, s_obj)
    if reused is not None:
        return reused
    code, result = execute(cfg, req.lineage, prompt.text, s_text)
    tool_events = audit_events(req.lineage, result.events)
    if tool_events:
        _incident(ws, req, "tool_event", tool_events)
        raise IsolationError(f"{req.identity}: tool event {tool_events[0]}; output discarded")
    if code is None:
        _incident(ws, req, "call_failed", [f"timed out after {cfg.timeout_s}s"])
        raise CallFailed(f"{req.identity}: CLI timed out after {cfg.timeout_s}s")
    if code != 0 or result.status != "success":
        _incident(ws, req, "call_failed", [result.detail or f"exit {code}, {result.status}"])
        raise CallFailed(f"{req.identity}: CLI failed ({result.detail or f'exit {code}'})")
    if req.lineage == "claude" and result.model != fingerprint["resolved_model"]:
        raise IntegrityError(f"{req.identity}: model {result.model} is not the qualified "
                             f"{fingerprint['resolved_model']}")
    output, problems = parse_output(result.text, s_obj, req.validate)
    if problems:
        _incident(ws, req, "invalid_output", problems[:10])
        raise CallFailed(f"{req.identity}: invalid output ({problems[0]})")
    store.write_json(record_path(ws, req), {
        "attempt_id": store.sha256_text(store.canonical(expect))[:16], "identity": req.identity,
        "stage": req.stage, "role": req.role, "lineage": req.lineage, "run": req.run, "era": req.era, **expect,
        "output": output, "events": [asdict(e) for e in result.events],
    })
    return output

