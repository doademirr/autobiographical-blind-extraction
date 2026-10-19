"""The fake CLIs' side of qualification's request capture: talk to the loopback provider.

Mirrors what the real CLIs were measured to do: send a request listing their tools,
run a scripted tool call by the rules of the locked or unlocked configuration, and send
the result back by call id. Switches:
  ABX_FAKE_CAPTURE_EXTRA_TOOL   list this extra tool in the locked registry
  ABX_FAKE_CAPTURE_RESULT       return this instead of the real result for scripted calls
"""

import json
import os
import re
import urllib.request

LOCKED_CODEX = ["exec", "wait", "request_user_input", "request_user_input_async"]
UNLOCKED_CODEX = [*LOCKED_CODEX, "spawn_agent"]
CODEX_LOCKED_RESULTS = {"exec": "code-mode host is disabled", "wait": "code-mode host is disabled",
                        "request_user_input": "request_user_input is unavailable in Default mode",
                        "request_user_input_async": '{"accepted":true}'}
CLAUDE_LOCKED_READ = ("<tool_use_error>Error: No such tool available: Read. Read is disabled for this session, "
                      "in subagents as well as here.</tool_use_error>")


def _post(url: str, body: dict) -> list[dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return [json.loads(line[6:]) for line in r.read().decode().splitlines() if line.startswith("data: ")]


def _config_values(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-c" and i + 1 < len(argv)]


def codex_endpoint(argv: list[str]) -> str | None:
    for value in _config_values(argv):
        m = (re.match(r'openai_base_url="(.+)"$', value)
             or re.search(r'model_providers\.\w+=.*base_url="([^"]+)"', value))
        if m:
            return m.group(1).rstrip("/") + "/responses"
    return None


def _override(real: str) -> str:
    return os.environ.get("ABX_FAKE_CAPTURE_RESULT", real)


def _codex_result(item: dict, locked: bool, argv: list[str]) -> tuple[str, list[dict]]:
    name = item.get("name")
    if locked:
        return _override(CODEX_LOCKED_RESULTS.get(name, f"unsupported call: {name}")), []
    script = item.get("input", "")
    cat = re.search(r'cat ([^"]+)"', script)
    if cat:
        with open(cat.group(1)) as f:
            text = f.read()
        return _override(json.dumps({"exit_code": 0, "output": text})), [
            {"type": "item.completed", "item": {"id": "i5", "type": "command_execution"}}]
    if "mcp__abxcanary__" in script:
        server = next(v for v in _config_values(argv) if v.startswith("mcp_servers.abxcanary="))
        token = re.search(r'args=\["[^"]+","([^"]+)"\]', server).group(1)
        return _override(json.dumps({"content": [{"type": "text", "text": token}]})), [
            {"type": "item.completed", "item": {"id": "i6", "type": "mcp_tool_call"}}]
    return "unsupported", []


def codex(argv: list[str], prompt: str, model: str, url: str) -> list[dict]:
    disabled = {argv[i + 1] for i, a in enumerate(argv) if a == "--disable"}
    locked = "shell_tool" in disabled
    names = list(LOCKED_CODEX if locked else UNLOCKED_CODEX)
    if locked and os.environ.get("ABX_FAKE_CAPTURE_EXTRA_TOOL"):
        names.append(os.environ["ABX_FAKE_CAPTURE_EXTRA_TOOL"])
    tools = [{"type": "namespace", "name": "functions", "tools": [{"type": "function", "name": n} for n in names]}]
    user = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}]}
    request = {"model": model, "input": [{"type": "additional_tools", "tools": tools}, user]}
    events = [{"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"}]
    for ev in _post(url, request):
        item = ev.get("item", {})
        if ev.get("type") == "response.output_item.done" and item.get("type") in {"function_call", "custom_tool_call"}:
            output, extra_events = _codex_result(item, locked, argv)
            events += extra_events
            out_type = "custom_tool_call_output" if item["type"] == "custom_tool_call" else "function_call_output"
            _post(url, {**request, "input": [*request["input"], item,
                                             {"type": out_type, "call_id": item["call_id"], "output": output}]})
    return [*events, {"type": "item.completed", "item": {"id": "i9", "type": "agent_message", "text": "DONE"}},
            {"type": "turn.completed", "usage": {}}]


def claude(argv: list[str], prompt: str, model: str, base: str) -> list[dict]:
    allowed = argv[argv.index("--tools") + 1].split(",") if "--tools" in argv else []
    names = [n for n in allowed if n]
    mcp_token = None
    if "--mcp-config" in argv:
        server = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]["abxcanary"]
        mcp_token = server["args"][1]
        names.append("mcp__abxcanary__read_canary")
    request = {"model": model, "tools": [{"name": n} for n in names],
               "messages": [{"role": "user", "content": prompt}]}
    stream = _post(base.rstrip("/") + "/v1/messages", request)
    block = next((e["content_block"] for e in stream if e.get("type") == "content_block_start"), {})
    events = [{"type": "system", "subtype": "init", "tools": names, "mcp_servers": [], "model": model}]
    if block.get("type") == "tool_use":
        args = json.loads(next(e["delta"]["partial_json"] for e in stream if e.get("type") == "content_block_delta"))
        if block["name"] not in names:
            result = CLAUDE_LOCKED_READ
        elif block["name"] == "Read":
            with open(args["file_path"]) as f:
                result = f.read()
        else:
            result = mcp_token
        events.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": block["name"]}]}})
        _post(base.rstrip("/") + "/v1/messages", {**request, "messages": [
            *request["messages"], {"role": "assistant", "content": [block]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": block["id"],
                                          "content": _override(result)}]}]})
    return [*events, {"type": "result", "subtype": "success", "is_error": False, "result": "DONE"}]
