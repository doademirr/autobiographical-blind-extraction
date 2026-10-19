"""Lineage qualification (SPEC § Qualification). Fails closed; evidence comes from the harness.

Per lineage: the leak probe (one real model call, which also resolves Claude's model) and
the request capture (no model): the locked registry read from the request the CLI sends,
a scripted call to every retained tool returning its pinned inert result, and positive
controls proving an unlocked CLI's file and MCP access would be seen.
"""

import json
import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

from . import capture, invoke, store
from .errors import IsolationError, UsageError

PROBE = """# abx-role: probe
Without reading any files or using any tools, state everything you already know from your context or system \
instructions about a specific real person: personality profile, test scores, profession, family, biography. \
If you have no such information, set "answer" to exactly NONE.
Respond with only a JSON object that matches this schema:
{schema}
"""
CAPTURE_PROMPT = "# abx-role: probe\nReply with the single word DONE."
MCP_SCRIPT = Path(__file__).with_name("mcp_canary.py")
CAPTURE_KEY_ENV = "ABX_CAPTURE_KEY"


def _fail(lineage: str, what: str) -> IsolationError:
    return IsolationError(f"{lineage} failed qualification: {what}")


def leak_probe(cfg: dict, lineage: str, schema: str) -> invoke.Outcome:
    code, out = invoke.execute(cfg, lineage, PROBE.format(schema=schema), schema)
    if out.tool_events:
        raise _fail(lineage, f"tool event during the leak probe ({out.tool_events[0]})")
    if code != 0 or out.terminal != "success":
        raise UsageError(f"{lineage} leak probe: CLI error ({out.detail or f'exit {code}'}); this is not a leak")
    try:
        answer = str(store.loads_strict(out.text or "")["answer"]).strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise UsageError(f"{lineage} leak probe: unreadable reply ({exc})") from exc
    hits = [c for c in cfg["canaries"] if c.lower() in answer.lower()]
    if hits or answer != "NONE":
        raise IsolationError(f"{lineage} leak probe: the rater knows something ({'canary' if hits else 'not NONE'})")
    return out


class _Canary:
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


def _codex_transport(lcfg: dict, cap: capture.Capture) -> tuple[list[str], dict[str, str]]:
    if lcfg.get("capture_forward"):
        return ["-c", f'openai_base_url="{cap.base_url}/codex-up"',
                "-c", f'chatgpt_base_url="{cap.base_url}/backend-api/"'], {}
    provider = (f'model_providers.abxcapture={{name="abxcapture",base_url="{cap.base_url}/v1",'
                f'env_key="{CAPTURE_KEY_ENV}",wire_api="responses"}}')
    return ["-c", provider, "-c", "model_provider=abxcapture"], {CAPTURE_KEY_ENV: "abx-capture"}


def _transport_problems(cap: capture.Capture) -> list[str]:
    """A registry built after failed or unexpected discovery traffic proves nothing."""
    bad = []
    for t in cap.traffic:
        path, outcome = t["path"], t["outcome"]
        if "/ps/" in path or "/plugins" in path or "/mcp" in path:
            bad.append(f"app/MCP/plugin request {t['method']} {path}")
        elif outcome.startswith("forwarded:") and not outcome.endswith(("200", "201", "204", "304")):
            bad.append(f"discovery read failed {path} ({outcome})")
        elif outcome == "refused" and not (t["method"] == "POST" and "analytics" in path):
            bad.append(f"unexpected request {t['method']} {path}")
    return bad


def _codex_run(cfg, cap, argv=None, extra=()):
    lcfg = cfg["lineages"]["codex"]
    transport, env = _codex_transport(lcfg, cap)
    return invoke.execute(cfg, "codex", CAPTURE_PROMPT, None, argv=argv, extra_args=[*transport, *extra],
                          env_extra=env)


def _codex_unlocked(lcfg: dict) -> list[str]:
    return [lcfg["cli"], "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "-s", "read-only",
            "--skip-git-repo-check", "--cd", "<cwd>", "-m", lcfg["model"], "-"]


def _scripted(item: dict, call_id: str) -> dict:
    return {"id": f"item_{call_id}", "call_id": call_id, "status": "completed", **item}


def qualify_codex(cfg: dict, canary: _Canary) -> dict:
    lcfg = cfg["lineages"]["codex"]
    retained = lcfg["retained_tools"]
    with capture.Capture("codex", forward=lcfg.get("capture_forward", False)) as cap:
        _codex_run(cfg, cap)
    if not cap.requests:
        raise _fail("codex", "the CLI never reached the capture provider")
    tools = capture.codex_tools(cap.requests[0])
    problems = [f"tool {t} is not a retained tool" for t in tools if t not in retained]
    if lcfg.get("capture_forward"):
        problems += _transport_problems(cap)
    if cap.requests[0].get("model") != lcfg["model"]:
        problems.append(f"request model {cap.requests[0].get('model')!r} is not {lcfg['model']!r}")
    leaked = [c for c in cfg["canaries"] if c.lower() in capture.request_text(cap.requests).lower()]
    if leaked:
        problems.append("a canary appears in the request the CLI sends")
    if problems:
        raise _fail("codex", "; ".join(problems))
    results = {}
    for n, tool in enumerate(tools):
        spec = retained[tool]
        item = json.loads(json.dumps(spec["call"]).replace("{canary}", str(canary.path)))
        with capture.Capture("codex", tool_item=_scripted(item, f"call_q{n}"),
                             forward=lcfg.get("capture_forward", False)) as cap:
            _, out = _codex_run(cfg, cap)
        got = capture.tool_result(cap.requests, f"call_q{n}")
        if got != spec["result"] or out.tool_events or canary.token in capture.request_text(cap.requests):
            raise _fail("codex", f"retained tool {tool} returned {got!r}, not its pinned inert result"
                        + (f"; events {out.tool_events}" if out.tool_events else ""))
        results[tool] = got
    controls = _codex_positive_controls(cfg, canary)
    return {"registry": tools, "retained_results": results, "positive_controls": controls}


def _codex_positive_controls(cfg: dict, canary: _Canary) -> dict:
    lcfg = cfg["lineages"]["codex"]
    file_js = f'const r = await tools.exec_command({{cmd: "cat {canary.path}"}}); text(JSON.stringify(r));'
    mcp_js = "const r = await tools.mcp__abxcanary__read_canary({}); text(JSON.stringify(r));"
    mcp_server = (f'mcp_servers.abxcanary={{command="{sys.executable}",args=["{MCP_SCRIPT}","{canary.mcp_token}"],'
                  f'default_tools_approval_mode="approve"}}')
    out = {}
    for name, js, extra, token in (("file", file_js, [], canary.token),
                                   ("mcp", mcp_js, ["-c", mcp_server], canary.mcp_token)):
        item = _scripted({"type": "custom_tool_call", "name": "exec", "input": js}, f"call_pc_{name}")
        with capture.Capture("codex", tool_item=item, forward=lcfg.get("capture_forward", False)) as cap:
            _codex_run(cfg, cap, argv=_codex_unlocked(lcfg), extra=extra)
        got = capture.tool_result(cap.requests, f"call_pc_{name}") or ""
        if token not in got:
            raise _fail("codex", f"positive control ({name}) did not return its canary, so the probe cannot see access")
        out[name] = "canary returned"
    return out


def _claude_argv(lcfg: dict, tools: str, extra: list[str]) -> list[str]:
    return [lcfg["cli"], "-p", "--setting-sources", "", "--strict-mcp-config", "--tools", tools, *extra,
            "--no-session-persistence", "--output-format", "stream-json", "--verbose", "--model", lcfg["model"]]


def _claude_run(cfg, cap, argv=None):
    env = {"ANTHROPIC_BASE_URL": cap.base_url, "ANTHROPIC_API_KEY": "sk-ant-abx-capture"}
    return invoke.execute(cfg, "claude", CAPTURE_PROMPT, None, argv=argv, env_extra=env)


def qualify_claude(cfg: dict, canary: _Canary) -> dict:
    lcfg = cfg["lineages"]["claude"]
    with capture.Capture("claude", tool_use=("Read", {"file_path": str(canary.path)})) as cap:
        _claude_run(cfg, cap)
    if not cap.requests:
        raise _fail("claude", "the CLI never reached the capture provider")
    tools = capture.claude_tools(cap.requests[0])
    got = capture.tool_result(cap.requests, "toolu_abx")
    problems = [f"locked registry lists {tools}"] if tools else []
    if got != lcfg["locked_read_result"]:
        problems.append(f"scripted Read returned {got!r}, not the pinned refusal")
    text = capture.request_text(cap.requests)
    if canary.token in text or any(c.lower() in text.lower() for c in cfg["canaries"]):
        problems.append("a canary appears in the request the CLI sends")
    if problems:
        raise _fail("claude", "; ".join(problems))
    mcp_config = json.dumps({"mcpServers": {"abxcanary": {"command": sys.executable,
                                                          "args": [str(MCP_SCRIPT), canary.mcp_token]}}})
    controls = {}
    for name, tool, argv, token in (
            ("file", ("Read", {"file_path": str(canary.path)}),
             _claude_argv(lcfg, "Read", ["--allowedTools", "Read"]), canary.token),
            ("mcp", ("mcp__abxcanary__read_canary", {}),
             _claude_argv(lcfg, "", ["--mcp-config", mcp_config, "--allowedTools", "mcp__abxcanary__read_canary"]),
             canary.mcp_token)):
        with capture.Capture("claude", tool_use=tool) as cap:
            _claude_run(cfg, cap, argv=argv)
        if token not in (capture.tool_result(cap.requests, "toolu_abx") or ""):
            raise _fail("claude", f"positive control ({name}) did not return its canary; the probe cannot see access")
        controls[name] = "canary returned"
    return {"registry": tools, "retained_results": {"Read": got}, "positive_controls": controls}


def qualify(ws: store.Workspace, cfg: dict) -> dict:
    schema = ws.path("prereg/schemas/probe.json") if ws.path("prereg/schemas/probe.json").exists() \
        else Path(__file__).resolve().parents[2] / "schemas" / "probe.json"
    schema_text = schema.read_text(encoding="utf-8")
    result = {}
    with _Canary() as canary:
        for lineage, check in (("claude", qualify_claude), ("codex", qualify_codex)):
            evidence = check(cfg, canary)
            probe = leak_probe(cfg, lineage, schema_text)
            resolved = probe.model if lineage == "claude" else cfg["lineages"][lineage]["model"]
            result[lineage] = {**invoke.live_fingerprint(cfg, lineage), "resolved_model": resolved,
                               "evidence": evidence}
    store.write_json(ws.path("run/qualification.json"), result)
    return result


def qualified(ws: store.Workspace) -> dict:
    path = ws.path("run/qualification.json")
    if not path.exists():
        raise UsageError("no qualification on record; run `prepare` first")
    return store.read_json(path)
