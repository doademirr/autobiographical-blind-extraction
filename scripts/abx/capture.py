"""Loopback fake model provider: records each request and answers with a scripted response.

No model is called. The first inference request is answered with the scripted tool call
(if any); every later one with a plain "DONE" message, so the CLI sends the tool's result
back and the harness can read it by call id. For Codex, non-inference GETs can be
forwarded to the real backend so the CLI builds its tools from real metadata; request
header values are never stored. Handler threads report to one recorder; after the server
stops, `Capture.evidence` is the immutable record.
"""

import http.server
import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import NamedTuple

__all__ = ["Capture", "Evidence", "Traffic", "claude_tools", "codex_tools", "messages_stream", "request_text",
           "responses_stream", "tool_output", "tool_text"]

CODEX_UPSTREAM = {"/codex-up/": "https://chatgpt.com/backend-api/codex/",
                  "/backend-api/": "https://chatgpt.com/backend-api/"}
_DROP_HEADERS = {"host", "content-length", "accept-encoding", "connection"}
_USAGE_RESPONSES = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                    "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}


class Traffic(NamedTuple):
    method: str
    path: str
    outcome: str            # "captured" | "forwarded" | "refused" | "ws-refused" | "unreadable"
    status: int | None = None


@dataclass(frozen=True)
class Evidence:
    requests: tuple[dict, ...]
    traffic: tuple[Traffic, ...]


class _Recorder:
    """The single owner of what handler threads observe."""

    def __init__(self):
        self._lock = threading.Lock()
        self._requests: list[dict] = []
        self._traffic: list[Traffic] = []

    def request(self, req: dict, path: str) -> int:
        with self._lock:
            self._requests.append(req)
            self._traffic.append(Traffic("POST", path, "captured"))
            return len(self._requests)

    def traffic(self, item: Traffic) -> None:
        with self._lock:
            self._traffic.append(item)

    def finish(self) -> Evidence:
        with self._lock:
            return Evidence(tuple(self._requests), tuple(self._traffic))


def _sse(events: list[dict]) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


def responses_stream(n: int, tool_item: dict | None) -> bytes:
    """Responses-API SSE (Codex): a tool-call item on the first request, else a message."""
    rid = f"resp_{n}"
    item = tool_item if (n == 1 and tool_item) else {
        "type": "message", "id": f"msg_{n}", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": "DONE", "annotations": []}]}
    return _sse([{"type": "response.created", "response": {"id": rid}},
                 {"type": "response.output_item.done", "output_index": 0, "item": item},
                 {"type": "response.completed", "response": {"id": rid, "usage": _USAGE_RESPONSES}}])


def messages_stream(n: int, model: str, tool: tuple[str, dict] | None) -> bytes:
    """Messages-API SSE (Claude): a tool_use block on the first request, else text."""
    msg = {"id": f"msg_{n}", "type": "message", "role": "assistant", "model": model, "content": [],
           "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
    if n == 1 and tool:
        block, delta, stop = ({"type": "tool_use", "id": "toolu_abx", "name": tool[0], "input": {}},
                              {"type": "input_json_delta", "partial_json": json.dumps(tool[1])}, "tool_use")
    else:
        block, delta, stop = {"type": "text", "text": ""}, {"type": "text_delta", "text": "DONE"}, "end_turn"
    return _sse([{"type": "message_start", "message": msg},
                 {"type": "content_block_start", "index": 0, "content_block": block},
                 {"type": "content_block_delta", "index": 0, "delta": delta},
                 {"type": "content_block_stop", "index": 0},
                 {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                  "usage": {"output_tokens": 1}},
                 {"type": "message_stop"}])


class Capture:
    """`with Capture("codex", tool_item=…) as cap:` point the CLI at `cap.base_url`; then read `cap.evidence`."""

    def __init__(self, lineage: str, tool_item: dict | None = None, tool_use: tuple[str, dict] | None = None,
                 forward: bool = False):
        self.lineage = lineage
        self.tool_item = tool_item      # Codex: a function_call / custom_tool_call item
        self.tool_use = tool_use        # Claude: (tool name, input)
        self.forward = forward          # Codex: forward GETs to the real backend
        self.evidence: Evidence | None = None
        self._recorder = _Recorder()

    def __enter__(self):
        cap, rec = self, self._recorder

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _send(self, code, body=b"", ctype="application/json"):
                self.send_response(code)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?")[0]
                if self.headers.get("Upgrade"):
                    rec.traffic(Traffic("GET", path, "ws-refused"))
                    return self._send(404)
                upstream = next((base + self.path[len(pre):] for pre, base in CODEX_UPSTREAM.items()
                                 if self.path.startswith(pre)), None)
                if not (cap.forward and upstream):
                    rec.traffic(Traffic("GET", path, "refused"))
                    return self._send(404)
                headers = {k: v for k, v in self.headers.items() if k.lower() not in _DROP_HEADERS}
                try:
                    with urllib.request.urlopen(urllib.request.Request(upstream, headers=headers), timeout=30) as r:
                        code, body, ctype = r.status, r.read(), r.headers.get("content-type", "application/json")
                except urllib.error.HTTPError as exc:
                    code, body, ctype = exc.code, exc.read(), "application/json"
                    exc.close()
                except OSError:
                    code, body, ctype = 502, b"", "application/json"
                rec.traffic(Traffic("GET", path, "forwarded", code))
                self._send(code, body, ctype)

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                path = self.path.split("?")[0]
                if path.endswith("/responses") or (path.endswith("/messages") and "count_tokens" not in path):
                    try:
                        req = json.loads(body)
                    except ValueError:
                        rec.traffic(Traffic("POST", path, "unreadable"))
                        return self._send(400)
                    n = rec.request(req if isinstance(req, dict) else {"_unexpected": req}, path)
                    stream = (responses_stream(n, cap.tool_item) if cap.lineage == "codex"
                              else messages_stream(n, req.get("model", "") if isinstance(req, dict) else "",
                                                   cap.tool_use))
                    return self._send(200, stream, "text/event-stream")
                if path.endswith("count_tokens"):
                    return self._send(200, b'{"input_tokens": 1}')
                rec.traffic(Traffic("POST", path, "refused"))
                self._send(404)

            def log_message(self, *args):
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
        self.evidence = self._recorder.finish()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def codex_tools(request: dict) -> list[str]:
    """Every tool name Codex offered, namespaced as `namespace.tool`."""
    top = list(request.get("tools") or [])
    for item in request.get("input", []):
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            top += item.get("tools", [])
    names: list[str] = []

    def walk(tools, prefix):
        for t in tools:
            name = t.get("name") or t.get("type")
            if isinstance(t.get("tools"), list):
                walk(t["tools"], f"{prefix}{name}.")
            else:
                names.append(f"{prefix}{name}")

    walk(top, "")
    return names


def claude_tools(request: dict) -> list[str]:
    return [t.get("name") for t in request.get("tools", [])]


_MISSING = object()


def tool_output(requests: tuple[dict, ...], call_id: str):
    """The tool output the CLI returned for `call_id`, exactly as sent; `_MISSING` if absent."""
    for req in requests[1:]:
        for item in req.get("input", []):
            is_output = isinstance(item, dict) and str(item.get("type", "")).endswith("_output")
            if is_output and item.get("call_id") == call_id:
                return item.get("output")
        for msg in req.get("messages", []):
            for block in msg.get("content", []) if isinstance(msg.get("content"), list) else []:
                if block.get("type") == "tool_result" and block.get("tool_use_id") == call_id:
                    return block.get("content")
    return _MISSING


def tool_text(requests: tuple[dict, ...], call_id: str) -> str:
    """The same output flattened to text, for canary searches."""
    out = tool_output(requests, call_id)
    return "" if out is _MISSING else json.dumps(out, ensure_ascii=False) if not isinstance(out, str) else out


def request_text(requests: tuple[dict, ...]) -> str:
    """Everything the CLI sent, as one string, for canary checks."""
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in requests)
