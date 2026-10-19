"""Fake `claude` and `codex` CLIs for the offline suite.

They answer `--version`, read the prompt on stdin, and print each lineage's event stream
around an output generated from the prompt (`roles.respond`). Environment switches inject
failures:
  ABX_FAKE_LOG          directory: every prompt is logged there, with call counters
  ABX_FAKE_VERSION      version string to report
  ABX_FAKE_TOOL_EVENT   emit this tool-event kind (see TOOL_EVENTS)
  ABX_FAKE_FAIL         end with a CLI failure
  ABX_FAKE_LEAK         answer the leak probe with this text
  ABX_FAKE_FAIL_AFTER   fail every call after this many successful ones (interruption)
  ABX_FAKE_RAW          print this string as the final message verbatim
"""

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roles

TOOL_EVENTS = {
    "claude": {
        "tool_use": lambda: {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}},
        "server_tool_use": lambda: {"type": "assistant", "message": {"content": [
            {"type": "server_tool_use", "id": "t1", "name": "web_search", "input": {}}]}},
        "tool_result": lambda: {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
        "unknown": lambda: {"type": "stream_event", "event": {}},
    },
    "codex": {k: (lambda k=k: {"type": "item.completed", "item": {"id": "i9", "type": k}})
              for k in ("command_execution", "file_change", "mcp_tool_call", "web_search", "todo_list",
                        "collab_tool_call", "image_view")}
    | {"unknown": lambda: {"type": "session.configured"}},
}


def _state(log: Path | None, lineage: str, prompt: str) -> tuple[int, int]:
    """(successful calls so far for this lineage, occurrences of this exact prompt so far)."""
    if log is None:
        return 0, 0
    path = log / f"state-{lineage}.json"
    state = json.loads(path.read_text()) if path.exists() else {"calls": 0, "prompts": {}}
    return state["calls"], state["prompts"].get(hashlib.sha256(prompt.encode()).hexdigest(), 0)


def _bump(log: Path | None, lineage: str, prompt: str) -> None:
    if log is None:
        return
    path = log / f"state-{lineage}.json"
    state = json.loads(path.read_text()) if path.exists() else {"calls": 0, "prompts": {}}
    key = hashlib.sha256(prompt.encode()).hexdigest()
    state["calls"] += 1
    state["prompts"][key] = state["prompts"].get(key, 0) + 1
    path.write_text(json.dumps(state))


def _arg(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv else None


def main(lineage: str) -> int:
    argv = sys.argv[1:]
    if "--version" in argv:
        print(os.environ.get("ABX_FAKE_VERSION", f"{lineage}-fake 1.0.0"))
        return 0
    prompt = sys.stdin.read()
    log = Path(os.environ["ABX_FAKE_LOG"]) if os.environ.get("ABX_FAKE_LOG") else None
    calls, occurrence = _state(log, lineage, prompt)
    if log is not None:
        log.mkdir(parents=True, exist_ok=True)
        with (log / "prompts.jsonl").open("a") as f:
            f.write(json.dumps({"lineage": lineage, "argv": argv, "prompt": prompt}) + "\n")
    fail_after = os.environ.get("ABX_FAKE_FAIL_AFTER")
    failing = bool(os.environ.get("ABX_FAKE_FAIL")) or (fail_after is not None and calls >= int(fail_after))
    model = _arg(argv, "--model") or _arg(argv, "-m") or "fake-model"
    if "ABX_FAKE_RAW" in os.environ:
        text = os.environ["ABX_FAKE_RAW"]
    else:
        text = json.dumps(roles.respond(prompt, lineage, occurrence, os.environ.get("ABX_FAKE_LEAK")))
    events = []
    injected = os.environ.get("ABX_FAKE_TOOL_EVENT")
    if lineage == "claude":
        events.append({"type": "system", "subtype": "init", "tools": [], "mcp_servers": [], "model": model})
        if injected:
            events.append(TOOL_EVENTS["claude"][injected]())
        events.append({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
        events.append({"type": "result", "subtype": "error_during_execution" if failing else "success",
                       "is_error": failing, "result": "fake failure" if failing else text})
    else:
        events += [{"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"},
                   {"type": "item.completed", "item": {"id": "i0", "type": "error",
                                                       "message": "Code Mode is unavailable"}}]
        if injected:
            events.append(TOOL_EVENTS["codex"][injected]())
        if failing:
            events.append({"type": "turn.failed", "error": {"message": "fake failure"}})
        else:
            events += [{"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": text}},
                       {"type": "turn.completed", "usage": {}}]
    for ev in events:
        print(json.dumps(ev))
    if failing:
        return 1
    _bump(log, lineage, prompt)
    return 0
