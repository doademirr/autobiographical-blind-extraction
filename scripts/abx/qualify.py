"""Lineage qualification (SPEC § Qualification). Fails closed; evidence comes from the harness.

Per lineage: the request capture (no model) and the leak probe (one recorded model call,
which also resolves Claude's model). Every locked capture passes the same complete
predicate: registry, request model, transport, canaries, CLI success, event audit, and,
for a scripted call, the tool's exact pinned result. Positive controls prove an unlocked
CLI's file and MCP access would be seen.
"""

import json
import os
import secrets
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import artifacts, capture, invoke, prompts, store
from . import schema as jsonschema
from .config import Config
from .errors import CallFailed, IsolationError, UsageError

__all__ = ["CAPTURE_PROMPT", "Canary", "leak_probe", "qualify", "qualify_claude", "qualify_codex"]

CAPTURE_PROMPT = "# abx-role: probe\nReply with the single word DONE."
MCP_SCRIPT = Path(__file__).with_name("mcp_canary.py")
CAPTURE_KEY_ENV = "ABX_CAPTURE_KEY"
CLAUDE_CALL_ID = "toolu_abx"
# A scripted Claude call shows as the tool_use it was told to make and the tool_result that answered it.
CLAUDE_SCRIPTED = frozenset({"assistant:tool_use", "user:"})


def _fail(lineage: str, what: str) -> IsolationError:
    return IsolationError(f"{lineage} failed qualification: {what}")


class Canary:
    """A canary file outside every allowlisted path, plus a separate token for the MCP control."""

    def __enter__(self):
        self.dir = Path(os.path.realpath(tempfile.mkdtemp(prefix="abx-canary-", dir=Path.home())))
        self.token = f"ABX-CANARY-{secrets.token_hex(6)}"
        self.mcp_token = f"ABX-MCP-CANARY-{secrets.token_hex(6)}"
        self.path = self.dir / "canary.txt"
        self.path.write_text(self.token)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)


@dataclass
class Capture:
    """One captured locked run: what the CLI sent, how it exited, and what it streamed."""

    cap: capture.Capture
    code: int | None
    result: invoke.Result
    problems: list[str] = field(default_factory=list)


def _canaries_in(text: str, cfg: Config, canary: Canary) -> list[str]:
    lowered = text.lower()
    return [c for c in (*cfg.canaries, canary.token, canary.mcp_token) if c.lower() in lowered]


def _transport_problems(cap: capture.Capture) -> list[str]:
    """A registry built after failed or unexpected discovery traffic proves nothing."""
    bad = []
    for t in cap.traffic:
        path, outcome = t["path"], t["outcome"]
        if "/ps/" in path or "/plugins" in path or "/mcp" in path:
            bad.append(f"app/MCP/plugin request {t['method']} {path}")
        elif outcome.startswith("forwarded:") and not outcome.endswith(("200", "201", "204", "304")):
            bad.append(f"discovery read failed {path} ({outcome})")
        elif outcome in {"refused", "unreadable"} and not (t["method"] == "POST" and "analytics" in path):
            bad.append(f"unexpected request {t['method']} {path}")
    return bad


def _locked_problems(lineage: str, cfg: Config, run: Capture, canary: Canary,
                     scripted: tuple[str, str] | None) -> list[str]:
    """The complete predicate for a locked capture; `scripted` is (call id, pinned result)."""
    lin = cfg.lineage(lineage)
    cap, problems = run.cap, []
    if not cap.requests:
        return ["the CLI never reached the capture provider"]
    if lineage == "codex":
        problems += [f"tool {t} is not a retained tool" for t in capture.codex_tools(cap.requests[0])
                     if t not in lin.retained_tools]
        problems += [f"request model {r.get('model')!r} is not {lin.model!r}" for r in cap.requests
                     if r.get("model") != lin.model]
        if lin.capture_forward:
            problems += _transport_problems(cap)
        allowed = frozenset()
    else:
        tools = capture.claude_tools(cap.requests[0])
        problems += [f"locked registry lists {tools}"] if tools else []
        allowed = CLAUDE_SCRIPTED if scripted else frozenset()
    if _canaries_in(capture.request_text(cap.requests), cfg, canary):
        problems.append("a canary appears in what the CLI sent")
    if run.code != 0 or run.result.status != "success":
        problems.append(f"the CLI did not finish cleanly (exit {run.code}, {run.result.status})")
    problems += [f"event {e}" for e in invoke.audit_events(lineage, run.result.events, allowed)]
    if scripted:
        got = capture.tool_result(cap.requests, scripted[0])
        if got != scripted[1]:
            problems.append(f"scripted call returned {got!r}, not its pinned inert result")
    return problems


def _codex_transport(cfg: Config, cap: capture.Capture) -> tuple[list[str], dict[str, str]]:
    if cfg.lineage("codex").capture_forward:
        return ["-c", f'openai_base_url="{cap.base_url}/codex-up"',
                "-c", f'chatgpt_base_url="{cap.base_url}/backend-api/"'], {}
    provider = (f'model_providers.abxcapture={{name="abxcapture",base_url="{cap.base_url}/v1",'
                f'env_key="{CAPTURE_KEY_ENV}",wire_api="responses"}}')
    return ["-c", provider, "-c", "model_provider=abxcapture"], {CAPTURE_KEY_ENV: "abx-capture"}


def _run_codex(cfg: Config, tool_item: dict | None = None, argv=None, extra=()) -> Capture:
    with capture.Capture("codex", tool_item=tool_item, forward=cfg.lineage("codex").capture_forward) as cap:
        transport, env = _codex_transport(cfg, cap)
        code, result = invoke.execute(cfg, "codex", CAPTURE_PROMPT, None, argv=argv,
                                      extra_args=[*transport, *extra], env_extra=env)
    return Capture(cap, code, result)


def _run_claude(cfg: Config, tool_use: tuple[str, dict] | None, argv=None) -> Capture:
    with capture.Capture("claude", tool_use=tool_use) as cap:
        env = {"ANTHROPIC_BASE_URL": cap.base_url, "ANTHROPIC_API_KEY": "sk-ant-abx-capture"}
        code, result = invoke.execute(cfg, "claude", CAPTURE_PROMPT, None, argv=argv, env_extra=env)
    return Capture(cap, code, result)


def _scripted(item: dict, call_id: str) -> dict:
    return {"id": f"item_{call_id}", "call_id": call_id, "status": "completed", **item}


def _require(lineage: str, problems: list[str]) -> None:
    if problems:
        raise _fail(lineage, "; ".join(problems))


def qualify_codex(cfg: Config, canary: Canary) -> dict:
    lin = cfg.lineage("codex")
    baseline = _run_codex(cfg)
    _require("codex", _locked_problems("codex", cfg, baseline, canary, None))
    tools = capture.codex_tools(baseline.cap.requests[0])
    results = {}
    for n, tool in enumerate(tools):
        spec = lin.retained_tools[tool]
        item = json.loads(json.dumps(spec["call"]).replace("{canary}", str(canary.path)))
        run = _run_codex(cfg, _scripted(item, f"call_q{n}"))
        _require("codex", [f"{tool}: {p}" for p in
                           _locked_problems("codex", cfg, run, canary, (f"call_q{n}", spec["result"]))])
        results[tool] = spec["result"]
    file_js = f'const r = await tools.exec_command({{cmd: "cat {canary.path}"}}); text(JSON.stringify(r));'
    mcp_js = "const r = await tools.mcp__abxcanary__read_canary({}); text(JSON.stringify(r));"
    mcp_server = (f'mcp_servers.abxcanary={{command="{sys.executable}",args=["{MCP_SCRIPT}","{canary.mcp_token}"],'
                  f'default_tools_approval_mode="approve"}}')
    controls = {}
    for name, js, extra, token in (("file", file_js, [], canary.token),
                                   ("mcp", mcp_js, ["-c", mcp_server], canary.mcp_token)):
        item = _scripted({"type": "custom_tool_call", "name": "exec", "input": js}, f"call_pc_{name}")
        run = _run_codex(cfg, item, argv=invoke.codex_argv(lin, locked=False), extra=extra)
        if token not in (capture.tool_result(run.cap.requests, f"call_pc_{name}") or ""):
            raise _fail("codex", f"positive control ({name}) did not return its canary; the probe cannot see access")
        controls[name] = "canary returned"
    return {"registry": tools, "retained_results": results, "positive_controls": controls}


def qualify_claude(cfg: Config, canary: Canary) -> dict:
    lin = cfg.lineage("claude")
    baseline = _run_claude(cfg, None)
    _require("claude", _locked_problems("claude", cfg, baseline, canary, None))
    scripted = _run_claude(cfg, ("Read", {"file_path": str(canary.path)}))
    _require("claude", [f"Read: {p}" for p in
                        _locked_problems("claude", cfg, scripted, canary, (CLAUDE_CALL_ID, lin.locked_read_result))])
    mcp_config = json.dumps({"mcpServers": {"abxcanary": {"command": sys.executable,
                                                          "args": [str(MCP_SCRIPT), canary.mcp_token]}}})
    controls = {}
    for name, tool, argv, token in (
            ("file", ("Read", {"file_path": str(canary.path)}),
             invoke.claude_argv(lin, "Read", ("--allowedTools", "Read")), canary.token),
            ("mcp", ("mcp__abxcanary__read_canary", {}),
             invoke.claude_argv(lin, "", ("--mcp-config", mcp_config, "--allowedTools", "mcp__abxcanary__read_canary")),
             canary.mcp_token)):
        run = _run_claude(cfg, tool, argv=argv)
        if token not in (capture.tool_result(run.cap.requests, CLAUDE_CALL_ID) or ""):
            raise _fail("claude", f"positive control ({name}) did not return its canary; the probe cannot see access")
        controls[name] = "canary returned"
    return {"registry": [], "retained_results": {"Read": lin.locked_read_result}, "positive_controls": controls}


def leak_probe(ws: store.Workspace, cfg: Config, lineage: str, canary: Canary) -> tuple[invoke.Result, dict]:
    """One recorded model call. A canary anywhere in the reply, or anything but NONE, is a leak (exit 3);
    a CLI failure, timeout or unreadable reply is a preflight failure (exit 2), never a pass."""
    prompt = prompts.assemble("probe", {"schema": "schema:probe"}, artifacts.resolver(ws))
    schema_text = artifacts.resolver(ws)("schema:probe")
    try:
        code, result = invoke.execute(cfg, lineage, prompt.text, schema_text)
    except CallFailed as exc:
        raise UsageError(f"{lineage} leak probe: {exc}; this is not a leak") from exc
    record = {"prompt_hash": store.sha256_text(prompt.text), "exit": code, "status": result.status,
              "events": [e.type + ":" + e.detail for e in result.events]}
    tool_events = invoke.audit_events(lineage, result.events)
    if tool_events:
        raise _fail(lineage, f"tool event during the leak probe ({tool_events[0]})")
    if _canaries_in(result.text or "", cfg, canary):
        raise IsolationError(f"{lineage} leak probe: a canary appears in the reply")
    if code is None:
        raise UsageError(f"{lineage} leak probe: CLI timed out; this is not a leak")
    if code != 0 or result.status != "success":
        raise UsageError(f"{lineage} leak probe: CLI error ({result.detail or f'exit {code}'}); this is not a leak")
    try:
        reply = store.loads_strict((result.text or "").strip())
    except ValueError as exc:
        raise UsageError(f"{lineage} leak probe: the reply is not JSON") from exc
    if jsonschema.errors(reply, store.loads_strict(schema_text)):
        raise UsageError(f"{lineage} leak probe: the reply does not match the probe schema")
    if reply["answer"].strip() != "NONE":
        raise IsolationError(f"{lineage} leak probe: the rater reports knowing something (not NONE)")
    return result, record


def qualify(ws: store.Workspace, cfg: Config, out: str = invoke.QUALIFICATION) -> dict:
    result = {}
    with Canary() as canary:
        for lineage, check in (("claude", qualify_claude), ("codex", qualify_codex)):
            evidence = check(cfg, canary)
            probe, probe_record = leak_probe(ws, cfg, lineage, canary)
            resolved = probe.model if lineage == "claude" else cfg.lineage(lineage).model
            result[lineage] = {**invoke.live_fingerprint(cfg, lineage), "resolved_model": resolved,
                               "evidence": {**evidence, "leak_probe": probe_record}}
    store.write_json(ws.path(out), result)
    return result
