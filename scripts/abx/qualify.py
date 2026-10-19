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
from dataclasses import dataclass
from pathlib import Path

from . import artifacts, capture, invoke, store
from .config import Config, retained
from .errors import IsolationError, UsageError

__all__ = ["Canary", "Run", "leak_control", "leak_probe", "qualify", "qualify_claude",
           "qualify_codex"]

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


@dataclass(frozen=True)
class Run:
    """One captured run: what the CLI sent, how it exited, and what it streamed."""

    evidence: capture.Evidence
    code: int | None
    result: invoke.Result


def _canaries_in(text: str, cfg: Config, canary: Canary) -> list[str]:
    lowered = text.lower()
    return [c for c in (*cfg.canaries, canary.token, canary.mcp_token) if c.lower() in lowered]


INFERENCE_PATH = "/codex-up/responses"
ANALYTICS_PATH = "/backend-api/codex/analytics-events/events"


def _transport_problems(evidence: capture.Evidence) -> list[str]:
    """A registry built after failed or unexpected discovery traffic proves nothing.

    Allowed: inference requests (captured), forwarded reads that succeed (2xx), the inference
    websocket upgrade refused (Codex falls back to HTTP), and the analytics POST refused.
    """
    bad = []
    for t in evidence.traffic:
        if "/ps/" in t.path or "/plugins" in t.path or "/mcp" in t.path:
            bad.append(f"app/MCP/plugin request {t.method} {t.path}")
        elif t.outcome == "forwarded" and not (t.status is not None and 200 <= t.status < 300):
            bad.append(f"discovery read failed {t.path} ({t.status})")
        elif t.outcome == "ws-refused" and t.path != INFERENCE_PATH:
            bad.append(f"unexpected websocket {t.path}")
        elif t.outcome in {"refused", "unreadable"} and not (t.method == "POST" and t.path == ANALYTICS_PATH):
            bad.append(f"unexpected request {t.method} {t.path}")
    return bad


def _locked_problems(lineage: str, cfg: Config, run: Run, canary: Canary,
                     scripted: tuple[str, str] | None, baseline: tuple[str, ...] | None = None) -> list[str]:
    """The complete predicate for a locked capture; `scripted` is (call id, pinned result).

    Every request the CLI sent is checked, not only the first, and once the baseline registry is
    known, every later capture must list exactly that registry, so no tool escapes its scripted test.
    """
    lin = cfg.lineage(lineage)
    requests, problems = run.evidence.requests, []
    if not requests:
        return ["the CLI never reached the capture provider"]
    if lineage == "codex":
        allowed_tools = set(retained(lin))
        try:
            registries = [tuple(sorted(capture.codex_tools(r))) for r in requests]
        except (AttributeError, TypeError):
            return ["a request's tool list is unreadable"]
        listed = {t for reg in registries for t in reg}
        problems += [f"tool {t} is not a retained tool" for t in sorted(listed - allowed_tools)]
        if len(set(registries)) > 1:
            problems.append("the tool list changed between requests")
        if baseline is not None and registries and registries[0] != baseline:
            problems.append("the tool list differs from the baseline capture's")
        problems += ["a request named another model" for r in requests if r.get("model") != lin.model][:1]
        if lin.capture_forward:
            problems += _transport_problems(run.evidence)
        allowed_events = frozenset()
    else:
        try:
            problems += ["a request listed tools" for r in requests if capture.claude_tools(r)][:1]
        except (AttributeError, TypeError):
            return ["a request's tool list is unreadable"]
        allowed_events = CLAUDE_SCRIPTED if scripted else frozenset()
    if _canaries_in(capture.request_text(requests), cfg, canary):
        problems.append("a canary appears in what the CLI sent")
    if run.code != 0 or run.result.status != "success":
        problems.append(f"the CLI did not finish cleanly (exit {run.code}, {run.result.status})")
    problems += [f"event {e}" for e in invoke.audit_events(lineage, run.result.events, allowed_events)]
    if scripted and capture.tool_output(requests, scripted[0]) != scripted[1]:
        problems.append("the scripted call did not return its exact pinned inert result")
    return problems


def _codex_transport(cfg: Config, cap: capture.Capture) -> tuple[list[str], dict[str, str]]:
    if cfg.lineage("codex").capture_forward:
        return ["-c", f'openai_base_url="{cap.base_url}/codex-up"',
                "-c", f'chatgpt_base_url="{cap.base_url}/backend-api/"'], {}
    provider = (f'model_providers.abxcapture={{name="abxcapture",base_url="{cap.base_url}/v1",'
                f'env_key="{CAPTURE_KEY_ENV}",wire_api="responses"}}')
    return ["-c", provider, "-c", "model_provider=abxcapture"], {CAPTURE_KEY_ENV: "abx-capture"}


def _run_codex(cfg: Config, prompt: str, tool_item: dict | None = None, argv=None, extra=()) -> Run:
    cap = capture.Capture("codex", tool_item=tool_item, forward=cfg.lineage("codex").capture_forward)
    with cap:
        transport, env = _codex_transport(cfg, cap)
        code, result = invoke.execute(cfg, "codex", prompt, None, argv=argv,
                                      extra_args=[*transport, *extra], env_extra=env)
    return Run(cap.evidence, code, result)


def _run_claude(cfg: Config, prompt: str, tool_use: tuple[str, dict] | None, argv=None) -> Run:
    cap = capture.Capture("claude", tool_use=tool_use)
    with cap:
        env = {"ANTHROPIC_BASE_URL": cap.base_url, "ANTHROPIC_API_KEY": "sk-ant-abx-capture"}
        code, result = invoke.execute(cfg, "claude", prompt, None, argv=argv, env_extra=env)
    return Run(cap.evidence, code, result)


def _scripted(item: dict, call_id: str) -> dict:
    return {"id": f"item_{call_id}", "call_id": call_id, "status": "completed", **item}


def _require(lineage: str, problems: list[str]) -> None:
    if problems:
        raise _fail(lineage, "; ".join(problems))


def qualify_codex(cfg: Config, canary: Canary, prompt: str) -> dict:
    lin = cfg.lineage("codex")
    pinned = retained(lin)
    baseline = _run_codex(cfg, prompt)
    _require("codex", _locked_problems("codex", cfg, baseline, canary, None))
    tools = tuple(sorted(capture.codex_tools(baseline.evidence.requests[0])))
    results = {}
    for n, tool in enumerate(tools):
        call, result = pinned[tool]
        item = json.loads(json.dumps(call).replace("{canary}", str(canary.path)))
        run = _run_codex(cfg, prompt, _scripted(item, f"call_q{n}"))
        _require("codex", [f"{tool}: {p}" for p in
                           _locked_problems("codex", cfg, run, canary, (f"call_q{n}", result), baseline=tools)])
        results[tool] = result
    file_js = f'const r = await tools.exec_command({{cmd: "cat {canary.path}"}}); text(JSON.stringify(r));'
    mcp_js = "const r = await tools.mcp__abxcanary__read_canary({}); text(JSON.stringify(r));"
    mcp_server = (f'mcp_servers.abxcanary={{command="{sys.executable}",args=["{MCP_SCRIPT}","{canary.mcp_token}"],'
                  f'default_tools_approval_mode="approve"}}')
    controls = {}
    for name, js, extra, token in (("file", file_js, [], canary.token),
                                   ("mcp", mcp_js, ["-c", mcp_server], canary.mcp_token)):
        item = _scripted({"type": "custom_tool_call", "name": "exec", "input": js}, f"call_pc_{name}")
        run = _run_codex(cfg, prompt, item, argv=invoke.codex_argv(lin, locked=False), extra=extra)
        if token not in capture.tool_text(run.evidence.requests, f"call_pc_{name}"):
            raise _fail("codex", f"positive control ({name}) did not return its canary; the probe cannot see access")
        controls[name] = "canary returned"
    return {"registry": list(tools), "retained_results": results, "positive_controls": controls}


def qualify_claude(cfg: Config, canary: Canary, prompt: str) -> dict:
    lin = cfg.lineage("claude")
    baseline = _run_claude(cfg, prompt, None)
    _require("claude", _locked_problems("claude", cfg, baseline, canary, None))
    scripted = _run_claude(cfg, prompt, ("Read", {"file_path": str(canary.path)}))
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
        run = _run_claude(cfg, prompt, tool, argv=argv)
        if token not in capture.tool_text(run.evidence.requests, CLAUDE_CALL_ID):
            raise _fail("claude", f"positive control ({name}) did not return its canary; the probe cannot see access")
        controls[name] = "canary returned"
    return {"registry": [], "retained_results": {"Read": lin.locked_read_result}, "positive_controls": controls}


def leak_probe(ws: store.Workspace, cfg: Config, lineage: str, canary: Canary) -> invoke.ProbeOutcome:
    """A canary anywhere in the stream, or anything but NONE, is a leak (exit 3); a CLI failure, timeout
    or unreadable reply is a preflight failure (exit 2), never a pass."""
    out = invoke.probe(ws, cfg, lineage, (*cfg.canaries, canary.token, canary.mcp_token))
    if out.verdict in {"leak", "isolation"}:
        raise IsolationError(f"{lineage} leak probe failed ({out.reason})")
    if out.verdict != "clean":
        raise UsageError(f"{lineage} leak probe could not complete ({out.reason}); this is not a leak")
    return out


def leak_control(ws: store.Workspace, cfg: Config, lineage: str) -> dict:
    """The leak probe's own positive control (one live model call): a rater handed an instruction file
    holding a canary must report it, so a NONE elsewhere means something."""
    out = invoke.probe(ws, cfg, lineage, cfg.canaries, mode="control")
    if out.verdict != "leak":
        raise IsolationError(f"{lineage} leak-probe control failed ({out.reason}); the probe cannot detect a leak")
    return out.record


def qualify(ws: store.Workspace, cfg: Config, out: str = invoke.QUALIFICATION) -> dict:
    prompt = artifacts.resolver(ws)("template:probe")
    result = {}
    with Canary() as canary:
        for lineage, check in (("claude", qualify_claude), ("codex", qualify_codex)):
            evidence = check(cfg, canary, prompt)
            probe = leak_probe(ws, cfg, lineage, canary)
            probe_record = probe.record
            resolved = probe.model if lineage == "claude" else cfg.lineage(lineage).model
            if not resolved:
                raise _fail(lineage, "no resolved model")
            result[lineage] = {**invoke.live_fingerprint(cfg, lineage), "resolved_model": resolved,
                               "evidence": {**evidence, "leak_probe": probe_record}}
    store.write_json(ws.path(out), result)
    return result
