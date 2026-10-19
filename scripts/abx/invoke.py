"""The only module that starts a model CLI.

Each call is a fresh process in an empty temp directory (also its process cwd: Codex
reads its launch directory), with only its prompt on stdin. Codex runs inside an OS
read sandbox. The event stream is audited against an allowlist of event kinds; any
other kind is a tool event and stops the stage. Only a validated success is recorded,
and a record is reused only when everything that produced it still matches.
"""

import json
import math
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import schema as jsonschema
from . import store
from .errors import CallFailed, IntegrityError, IsolationError, UsageError
from .prompts import Prompt

SYSTEM_READ_ROOTS = [
    "/System", "/usr", "/bin", "/sbin", "/Library/Apple", "/private/etc", "/private/var/db/dyld",
    "/dev", "/Library/Preferences/SystemConfiguration",
]
BASE_ENV_KEYS = ["PATH", "HOME", "LANG", "TMPDIR", "USER", "LOGNAME"]
CLAUDE_TEXT_BLOCKS = {"text", "thinking", "redacted_thinking"}
CODEX_ITEMS = {"agent_message", "reasoning", "error"}
CODEX_LIFECYCLE = {"thread.started", "turn.started"}


def sandbox_profile(allow: list[str]) -> str:
    """Deny every file read except system runtime paths and the given (canonicalised) roots.

    The root directory itself must be readable or dyld aborts; metadata reads stay allowed
    so paths resolve.
    """
    def subpaths(paths):
        return " ".join(f'(subpath "{os.path.realpath(p)}")' for p in paths)

    return (
        "(version 1)\n(allow default)\n(deny file-read*)\n(allow file-read-metadata)\n"
        f'(allow file-read* (literal "/") {subpaths(SYSTEM_READ_ROOTS)})\n'
        f"(allow file-read* {subpaths(allow)})\n"
    )


@dataclass
class Outcome:
    terminal: str | None = None          # "success" | "failed"
    text: str | None = None
    model: str | None = None
    tool_events: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    detail: str = ""


def parse_claude(lines: list[str]) -> Outcome:
    out = Outcome()
    for line in lines:
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            out.tool_events.append("unparseable-event")
            continue
        etype, sub = ev.get("type"), ev.get("subtype")
        out.kinds.append(f"{etype}/{sub}" if sub else str(etype))
        if etype == "system" and sub == "init":
            out.model = ev.get("model")
            if ev.get("tools") or ev.get("mcp_servers"):
                out.tool_events.append(f"init-registry:{ev.get('tools')}:{ev.get('mcp_servers')}")
        elif etype == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") not in CLAUDE_TEXT_BLOCKS:
                    out.tool_events.append(f"assistant-block:{block.get('type')}")
        elif etype == "result":
            ok = sub == "success" and not ev.get("is_error")
            out.terminal = "success" if ok else "failed"
            out.text = ev.get("result") if ok else None
            out.detail = "" if ok else str(ev.get("result") or sub)[:300]
        else:
            out.tool_events.append(f"event:{etype}/{sub}")
    return out


def parse_codex(lines: list[str]) -> Outcome:
    out = Outcome()
    for line in lines:
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue  # Codex prints plain-text log lines; only JSON lines are events
        etype = ev.get("type")
        out.kinds.append(str(etype))
        if etype in CODEX_LIFECYCLE or etype == "error":
            continue
        if etype in {"item.started", "item.updated", "item.completed"}:
            item = ev.get("item", {})
            if item.get("type") not in CODEX_ITEMS:
                out.tool_events.append(f"item:{item.get('type')}")
            elif item.get("type") == "agent_message" and etype == "item.completed":
                out.text = item.get("text")
        elif etype == "turn.completed":
            out.terminal = "success"
        elif etype == "turn.failed":
            out.terminal = "failed"
            out.detail = str(ev.get("error"))[:300]
        else:
            out.tool_events.append(f"event:{etype}")
    return out


@dataclass(frozen=True)
class CallSpec:
    stage: str
    role: str
    lineage: str
    run: int | None
    era: str | None
    generation: str
    schema_name: str
    prompt: Prompt
    validate: Callable[[object], list[str]] | None = None

    @property
    def identity(self) -> str:
        return f"{self.stage}/{self.role}/{self.lineage}-r{self.run or 0}-{self.era or 'all'}"


def record_path(ws: store.Workspace, spec: CallSpec) -> Path:
    return ws.path(f"run/calls/{spec.identity}.json")


def schema_text(ws: store.Workspace, name: str) -> str:
    return ws.path(f"prereg/schemas/{name}.json").read_text(encoding="utf-8")


def cli_version(cli: str) -> str:
    try:
        p = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UsageError(f"cannot run {cli} --version: {exc}") from exc
    if p.returncode != 0:
        raise UsageError(f"{cli} --version exited {p.returncode}")
    return p.stdout.strip()


def argv_template(lcfg: dict, lineage: str) -> list[str]:
    """The pinned argv with placeholders; its hash is the fingerprint's invocation hash."""
    if lineage == "claude":
        return [lcfg["cli"], "-p", "--setting-sources", "", "--strict-mcp-config", "--tools", "",
                "--no-session-persistence", "--output-format", "stream-json", "--verbose",
                "--model", lcfg["model"]]
    flags = [x for f in lcfg["disable"] for x in ("--disable", f)]
    flags += [x for c in lcfg["config"] for x in ("-c", c)]
    return [lcfg["sandbox_exec"], "-f", "<profile>", lcfg["cli"], "exec", "--json", "--ephemeral",
            "--ignore-user-config", "--ignore-rules", "-s", "read-only", "--skip-git-repo-check",
            "--cd", "<cwd>", "--output-schema", "<schema>", "-m", lcfg["model"], *flags, "-"]


def live_fingerprint(cfg: dict, lineage: str) -> dict:
    lcfg = cfg["lineages"][lineage]
    return {
        "cli": lcfg["cli"],
        "cli_version": cli_version(lcfg["cli"]),
        "invocation_hash": store.sha256_text(store.canonical(argv_template(lcfg, lineage))),
        "config_hash": store.sha256_text(store.canonical(lcfg)),
    }


def check_fingerprint(cfg: dict, lineage: str, qualified: dict) -> dict:
    live = live_fingerprint(cfg, lineage)
    changed = [k for k, v in live.items() if qualified.get(k) != v]
    if changed:
        raise IntegrityError(f"{lineage} fingerprint changed since qualification: {', '.join(changed)}")
    return {**live, "resolved_model": qualified.get("resolved_model")}


def _env(cfg: dict, extra: dict[str, str]) -> dict[str, str]:
    keys = BASE_ENV_KEYS + cfg.get("env_passthrough", [])
    return {**{k: os.environ[k] for k in keys if k in os.environ}, **extra}


def run_cli(argv: list[str], prompt: str, cwd: Path, env: dict[str, str], timeout: int) -> tuple[int, list[str]]:
    try:
        p = subprocess.run(argv, input=prompt, capture_output=True, text=True, cwd=cwd, env=env, check=False,
                           timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise CallFailed(f"CLI timed out after {timeout}s") from exc
    except OSError as exc:
        raise CallFailed(f"CLI could not start: {exc}") from exc
    return p.returncode, p.stdout.splitlines()


def execute(cfg: dict, lineage: str, prompt_text: str, schema: str | None,
            unlocked_argv: list[str] | None = None, env_extra: dict[str, str] | None = None) -> tuple[int, Outcome]:
    """One isolated CLI process. `unlocked_argv` replaces the pinned argv (qualification only)."""
    lcfg = cfg["lineages"][lineage]
    tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="abx-")))
    try:
        cwd = tmp / "cwd"
        cwd.mkdir()
        env = _env(cfg, env_extra or {})
        if lineage == "claude":
            argv = unlocked_argv or argv_template(lcfg, lineage)
            code, lines = run_cli(argv, prompt_text, cwd, env, cfg["timeout_s"])
            return code, parse_claude(lines)
        home = tmp / "home"
        home.mkdir()
        shutil.copy(os.path.expanduser(lcfg["auth_file"]), home / "auth.json")
        (tmp / "profile.sb").write_text(sandbox_profile([*lcfg["sandbox_allow"], str(tmp)]))
        (tmp / "schema.json").write_text(schema or "{}")
        argv = unlocked_argv or argv_template(lcfg, lineage)
        argv = [{"<profile>": str(tmp / "profile.sb"), "<cwd>": str(cwd),
                 "<schema>": str(tmp / "schema.json")}.get(a, a) for a in argv]
        code, lines = run_cli(argv, prompt_text, cwd, {**env, "CODEX_HOME": str(home)}, cfg["timeout_s"])
        return code, parse_codex(lines)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4 * 1.2)


def check_budget(cfg: dict, spec: CallSpec) -> None:
    lcfg = cfg["lineages"][spec.lineage]
    need = estimate_tokens(spec.prompt.text) + lcfg["reserve_output_tokens"]
    if need > lcfg["input_budget_tokens"]:
        raise UsageError(f"{spec.role} input for {spec.lineage} needs ~{need} tokens, "
                         f"over the {lcfg['input_budget_tokens']} budget")


def _parse_output(text: str | None, schema: dict, validate) -> tuple[object, list[str]]:
    if text is None:
        return None, ["no final message"]
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`").removeprefix("json").strip()
    try:
        out = store.loads_strict(body)
    except ValueError as exc:
        return None, [f"output is not JSON: {exc}"]
    problems = jsonschema.errors(out, schema)
    if not problems and validate:
        problems = validate(out)
    return out, problems


def _reusable(path: Path, expect: dict, schema: dict, validate) -> object:
    if not path.exists():
        return None
    rec = store.read_json(path)
    if any(rec.get(k) != v for k, v in expect.items()):
        return None
    _, problems = _parse_output(store.canonical(rec["output"]), schema, validate)
    return None if problems else rec["output"]


def _incident(ws: store.Workspace, spec: CallSpec, kind_: str, detail) -> None:
    store.write_json(ws.path(f"run/incidents/{spec.identity}.json"),
                     {"identity": spec.identity, "kind": kind_, "detail": detail})


def call(ws: store.Workspace, cfg: dict, spec: CallSpec, qualified: dict) -> object:
    """Run (or reuse) one model call and return its validated output."""
    fingerprint = check_fingerprint(cfg, spec.lineage, qualified)
    check_budget(cfg, spec)
    s_text = schema_text(ws, spec.schema_name)
    s_obj = store.loads_strict(s_text)
    expect = {
        "generation": spec.generation, "fingerprint": fingerprint, "input_artifacts": spec.prompt.artifacts,
        "schema_hash": store.sha256_text(s_text), "prompt_hash": store.sha256_text(spec.prompt.text),
    }
    path = record_path(ws, spec)
    reused = _reusable(path, expect, s_obj, spec.validate)
    if reused is not None:
        return reused
    code, outcome = execute(cfg, spec.lineage, spec.prompt.text, s_text)
    if outcome.tool_events:
        _incident(ws, spec, "tool_event", outcome.tool_events)
        raise IsolationError(f"{spec.identity}: tool event {outcome.tool_events[0]}; output discarded")
    if code != 0 or outcome.terminal != "success":
        _incident(ws, spec, "call_failed", outcome.detail or f"exit {code}, terminal {outcome.terminal}")
        raise CallFailed(f"{spec.identity}: CLI failed ({outcome.detail or f'exit {code}'})")
    if spec.lineage == "claude" and outcome.model != fingerprint["resolved_model"]:
        raise IntegrityError(f"{spec.identity}: model {outcome.model} is not the qualified "
                             f"{fingerprint['resolved_model']}")
    output, problems = _parse_output(outcome.text, s_obj, spec.validate)
    if problems:
        _incident(ws, spec, "invalid_output", problems[:10])
        raise CallFailed(f"{spec.identity}: invalid output ({problems[0]})")
    store.write_json(path, {
        "attempt_id": store.sha256_text(store.canonical(expect))[:16], "identity": spec.identity,
        "role": spec.role, "lineage": spec.lineage, "run": spec.run, "era": spec.era, **expect,
        "output": output, "events": outcome.kinds,
    })
    return output
