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
import secrets
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

__all__ = [
    "QUALIFICATION",
    "QUALIFICATION_A",
    "CallRequest",
    "Event",
    "ProbeOutcome",
    "Result",
    "audit_events",
    "call",
    "check_fingerprint",
    "claude_argv",
    "codex_argv",
    "estimate_tokens",
    "execute",
    "live_fingerprint",
    "parse_claude",
    "parse_codex",
    "probe",
    "qualified",
    "record_path",
    "sandbox_profile",
    "succeeded",
]

SYSTEM_READ_ROOTS = (
    "/System", "/usr/lib", "/usr/libexec", "/usr/bin", "/usr/sbin", "/usr/share", "/bin", "/sbin",
    "/Library/Apple", "/private/etc", "/private/var/db/dyld", "/dev", "/Library/Preferences/SystemConfiguration",
)
BASE_ENV_KEYS = ("PATH", "HOME", "LANG", "TMPDIR", "USER", "LOGNAME")
CLAUDE_TEXT_BLOCKS = {"text", "thinking", "redacted_thinking"}
CODEX_ITEMS = {"agent_message", "reasoning", "error"}
CODEX_LIFECYCLE = {"thread.started", "turn.started"}
CODEX_PLAIN_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\S+\s|Reading additional input from stdin)")
QUALIFICATION = "run/qualification.json"          # the current qualification, until generation A
QUALIFICATION_A = "prereg/qualification-A.json"   # the frozen baseline every later call is held to
FIRST_ERA_MARKER = "(none: this is the first era)"


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
    text: str | None = None         # the final message, the only one parsed as output
    model: str | None = None
    detail: str = ""
    events: list[Event] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)   # every assistant text seen, for leak scans only


_SAFE = re.compile(r"[^A-Za-z0-9_.:/-]")


def _safe(kind: str) -> str:
    """CLI-supplied event metadata, reduced to a short identifier before it reaches any diagnostic."""
    return _SAFE.sub("?", kind)[:64]


def audit_events(lineage: str, events: list[Event], allowed: frozenset[str] = frozenset()) -> list[str]:
    """Tool events in a stream: every event kind outside the lineage's allowlist, plus `allowed` exceptions.

    A Claude stream must open with its init event; without it there is no registry evidence.
    """
    found = []
    if lineage == "claude" and not any(ev.type == "system" and ev.detail == "init" for ev in events):
        found.append("no-init-event")
    for ev in events:
        kind = f"{ev.type}:{ev.detail}"
        if kind in allowed:
            continue
        if lineage == "claude":
            if ev.type == "system" and ev.detail == "init":
                if not ev.registry_present or ev.tools or ev.mcp_servers:
                    found.append(f"init-registry:{len(ev.tools)}-tools:{len(ev.mcp_servers)}-servers")
            elif ev.type == "assistant":
                found += [_safe(f"assistant-block:{b}") for b in ev.detail.split(",")
                          if b and b not in CLAUDE_TEXT_BLOCKS]
            elif ev.type != "result":
                found.append(_safe(kind))
        elif ev.type in CODEX_LIFECYCLE or ev.type in {"error", "turn.completed", "turn.failed"}:
            continue
        elif ev.type in {"item.started", "item.updated", "item.completed"}:
            if ev.detail not in CODEX_ITEMS:
                found.append(_safe(kind))
        else:
            found.append(_safe(kind))
    return found


def succeeded(lineage: str, events: list[Event]) -> bool:
    """Terminal success, read from the recorded stream itself."""
    if lineage == "claude":
        return any(e.type == "system" and e.detail == "init" for e in events) and \
            any(e.type == "result" and e.detail == "success" for e in events)
    return any(e.type == "turn.completed" for e in events) and not any(e.type == "turn.failed" for e in events)


def _strings(value) -> tuple[str, ...] | None:
    return tuple(str(v) for v in value) if isinstance(value, list) else None


def parse_claude(lines: list[str]) -> Result:
    out = Result()
    for line in lines:
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            ev = None
        if not isinstance(ev, dict):
            out.events.append(Event("unparseable"))
            continue
        etype, sub = str(ev.get("type")), ev.get("subtype")
        if etype == "system" and sub == "init":
            out.model = ev.get("model") if isinstance(ev.get("model"), str) else None
            tools, servers = _strings(ev.get("tools")), _strings(ev.get("mcp_servers"))
            out.events.append(Event("system", "init", tools or (), servers or (),
                                    registry_present=tools is not None and servers is not None))
        elif etype == "assistant":
            message = ev.get("message")
            blocks = message.get("content") if isinstance(message, dict) else None
            if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks):
                out.events.append(Event("unparseable"))
                continue
            out.events.append(Event("assistant", ",".join(str(b.get("type")) for b in blocks)))
            out.messages += [b[k] for b in blocks for k in ("text", "thinking") if isinstance(b.get(k), str)]
        elif etype == "result":
            out.events.append(Event("result", str(sub)))
            ok = sub == "success" and ev.get("is_error") is False and isinstance(ev.get("result"), str)
            out.status = "success" if ok else "failed"
            out.text = ev["result"] if ok else None
            out.detail = "" if ok else f"result {sub}"
        else:
            out.events.append(Event(etype, str(sub or "")))
    return out


def _texts(value) -> list[str]:
    """Every string inside a nested item field, for leak scans."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [t for v in value for t in _texts(v)]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _texts(v)]
    return []


def parse_codex(lines: list[str]) -> Result:
    out = Result()
    for line in lines:
        stripped = line.strip()
        if not stripped or CODEX_PLAIN_LINE.match(stripped):
            continue
        try:
            ev = json.loads(stripped)
        except ValueError:
            ev = None
        if not isinstance(ev, dict):
            out.events.append(Event("unparseable"))
            continue
        etype = str(ev.get("type"))
        item = ev.get("item") if isinstance(ev.get("item"), dict) else {}
        out.events.append(Event(etype, str(item.get("type", ""))))
        text = item.get("text")
        if item:
            out.messages += [v for k in ("text", "summary", "content") for v in _texts(item.get(k))]
        if etype == "item.completed" and item.get("type") == "agent_message":
            out.text = text if isinstance(text, str) else None
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
        "config_hash": store.sha256_text(lin.raw_json),
    }


def qualified(ws: store.Workspace) -> dict:
    """The qualification calls are held to: the frozen baseline once generation A exists."""
    for rel in (QUALIFICATION_A, QUALIFICATION):
        if ws.path(rel).exists():
            return store.read_json(ws.path(rel))
    raise UsageError("no qualification on record; run `prepare` first")


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
            extra_args: list[str] | None = None, env_extra: dict[str, str] | None = None,
            cwd_files: dict[str, str] | None = None) -> tuple[int | None, Result]:
    """One isolated CLI process; returns its exit code (None on timeout) and parsed stream.

    Qualification alone passes `argv` (an unlocked variant), `extra_args` (provider overrides,
    inserted before Codex's trailing stdin marker) or `cwd_files` (the leak probe's own control);
    model calls always use the pinned argv in an empty directory.
    """
    lin = cfg.lineage(lineage)
    argv = list(argv or _pinned_argv(lin))
    if extra_args:
        argv = [*argv[:-1], *extra_args, argv[-1]] if argv[-1] == "-" else [*argv, *extra_args]
    tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="abx-")))
    try:
        cwd = tmp / "cwd"
        cwd.mkdir()
        for name, body in (cwd_files or {}).items():
            (cwd / name).write_text(body)
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
    validate: Callable[[object], list[str]] | None = None

    @property
    def identity(self) -> str:
        return f"{self.stage}/{self.role}/{self.lineage}-r{self.run or 0}-{self.era or 'all'}"


def record_path(ws: store.Workspace, req: CallRequest) -> Path:
    return ws.path(f"run/calls/{req.identity}.json")


def _eras(ws: store.Workspace) -> list[dict]:
    path = ws.path("prepare/eras.json")
    return store.read_json(path)["eras"] if path.exists() else []


def _labels(ws: store.Workspace, req: CallRequest) -> dict[str, str]:
    """The labels a role's template takes, derived from the workspace, never from the caller."""
    policy = get_role(req.role)
    eras = _eras(ws)
    labels = {}
    if "era_label" in policy.params:
        era = next((e for e in eras if e["id"] == req.era), None)
        if era is None:
            raise UsageError(f"{req.role} call names an unknown era")
        labels["era_label"] = era["label"] or era["id"]
    if "hypotheses" in policy.params and "hypotheses" not in req.slots:
        if not eras or eras[0]["id"] != req.era:
            raise IsolationError(f"{req.role} for a later era must carry its own earlier hypotheses")
        labels["hypotheses"] = FIRST_ERA_MARKER
    return labels


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
    """A record is reused only when it is this call's, succeeded, matches every input and re-audits clean."""
    path = record_path(ws, req)
    if not path.exists():
        return None
    rec = store.read_json(path)
    identity = {"identity": req.identity, "stage": req.stage, "role": req.role, "lineage": req.lineage,
                "run": req.run, "era": req.era}
    if not isinstance(rec, dict) or any(rec.get(k) != v for k, v in {**identity, **expect}.items()):
        return None
    try:
        events = [Event(str(e["type"]), str(e["detail"]), tuple(map(str, e["tools"])),
                        tuple(map(str, e["mcp_servers"])), bool(e["registry_present"])) for e in rec["events"]]
    except (KeyError, TypeError, AttributeError):
        return None
    if audit_events(req.lineage, events):
        raise IsolationError(f"{req.identity}: its record holds a tool event; it cannot be reused")
    if not succeeded(req.lineage, events):
        return None
    _, problems = parse_output(store.canonical(rec["output"]), schema, req.validate)
    return None if problems else rec["output"]


def call(ws: store.Workspace, cfg: Config, req: CallRequest) -> object:
    """Assemble, audit, run (or reuse) one model call and return its validated output."""
    rater = (req.lineage, req.run) if req.run is not None else None
    slots = {**req.slots, "schema": f"schema:{get_role(req.role).schema}"}
    revealed = "C" in store.frozen_generations(ws)
    prompt = prompts.assemble(req.role, slots, artifacts.resolver(ws), _labels(ws, req), rater=rater, era=req.era,
                              era_order=[e["id"] for e in _eras(ws)], revealed=revealed)
    prompts.audit(prompt, withheld.load(ws), after_blind_results=revealed)
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
    if req.lineage == "claude" and (not result.model or result.model != fingerprint["resolved_model"]):
        raise IntegrityError(f"{req.identity}: model {result.model} is not the qualified "
                             f"{fingerprint['resolved_model']}")
    output, problems = parse_output(result.text, s_obj, req.validate)
    if problems:
        _incident(ws, req, "invalid_output", problems[:10])
        raise CallFailed(f"{req.identity}: invalid output ({problems[0]})")
    store.write_json(record_path(ws, req), {
        "attempt_id": store.sha256_text(store.canonical(expect))[:16], "identity": req.identity,
        "stage": req.stage, "role": req.role, "lineage": req.lineage, "run": req.run, "era": req.era,
        "status": "success", **expect,
        "output": output, "events": [asdict(e) for e in result.events],
    })
    return output


PROBE_MODES = ("leak", "control")


@dataclass(frozen=True)
class ProbeOutcome:
    """A leak probe's verdict: `clean`, `leak` (exit 3), `isolation` (exit 3) or `error` (exit 2, never a pass)."""

    verdict: str
    reason: str
    model: str | None
    record: dict


def _control_argv(lin: Lineage) -> list[str]:
    """The probe's positive control: the CLI as an ordinary user runs it, so it reads instruction files."""
    if lin.name == "claude":
        return [lin.cli, "-p", "--tools", "", "--no-session-persistence", "--output-format", "stream-json", "--verbose",
                "--model", lin.model]
    return [lin.cli, "exec", "--json", "--ephemeral", "-s", "read-only", "--skip-git-repo-check", "--cd", "<cwd>",
            "-m", lin.model, "-"]


def probe(ws: store.Workspace, cfg: Config, lineage: str, canaries: tuple[str, ...],
          mode: str = "leak") -> ProbeOutcome:
    """The one probe boundary. `leak` runs the pinned invocation in an empty directory and passes only on
    exactly NONE with no canary anywhere in the stream. `control` plants an instruction file holding a fresh
    canary and runs the CLI unlocked; it passes only if that canary is reported. Every probe is recorded,
    without reply content, at run/probes/<mode>-<lineage>.json."""
    if mode not in PROBE_MODES:
        raise UsageError(f"unknown probe mode {mode!r}")
    prompt = prompts.assemble("probe", {"schema": "schema:probe"}, artifacts.resolver(ws))
    schema_text = artifacts.resolver(ws)("schema:probe")
    lin = cfg.lineage(lineage)
    planted = f"ABXLEAKCONTROL{secrets.token_hex(4).upper()}"
    note = f"The user you are working for is codenamed {planted}; their personality type is known.\n"
    argv, files = (None, None) if mode == "leak" else (_control_argv(lin), {"CLAUDE.md": note, "AGENTS.md": note})
    looked_for = (*canaries, planted) if mode == "control" else canaries
    try:
        code, result = execute(cfg, lineage, prompt.text, schema_text, argv=argv, cwd_files=files)
    except CallFailed:
        code, result = -1, Result(status="failed")
    seen = "\n".join([*result.messages, result.text or ""]).lower()
    verdict, reason = _probe_verdict(lineage, code, result, schema_text,
                                     any(c.lower() in seen for c in looked_for), mode)
    record = {"mode": mode, "lineage": lineage, "verdict": verdict, "reason": reason,
              "prompt_hash": store.sha256_text(prompt.text), "exit": code, "status": result.status,
              "events": [_safe(f"{e.type}:{e.detail}") for e in result.events]}
    store.write_json(ws.path(f"run/probes/{mode}-{lineage}.json"), record)
    return ProbeOutcome(verdict, reason, result.model, record)


def _probe_verdict(lineage: str, code: int | None, result: Result, schema_text: str, canary_seen: bool,
                   mode: str) -> tuple[str, str]:
    if mode == "control":
        return ("leak", "canary_reported") if canary_seen else ("error", "control_canary_not_reported")
    if audit_events(lineage, result.events):
        return "isolation", "tool_event"
    if canary_seen:
        return "leak", "canary"
    if code is None:
        return "error", "timeout"
    if code != 0 or result.status != "success":
        return "error", "cli_failed"
    if lineage == "claude" and not result.model:
        return "error", "no_model"
    if result.text is None:
        return "error", "no_final_message"
    try:
        reply = store.loads_strict(result.text.strip())
    except ValueError:
        return "error", "not_json"
    if jsonschema.errors(reply, store.loads_strict(schema_text)):
        return "error", "schema"
    return ("clean", "none") if reply["answer"].strip() == "NONE" else ("leak", "not_none")
