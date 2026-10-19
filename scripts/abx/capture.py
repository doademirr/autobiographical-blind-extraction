"""Loopback fake model provider: records each request and answers with a scripted response.

No model is called. The first inference request is answered with the scripted tool call
(if any); every later one with a plain "DONE" message, so the CLI sends the tool's result
back and the harness can read it by call id. For Codex, non-inference GETs can be
forwarded to the real backend so the CLI builds its tools from real metadata; request
header values are never stored. Handler threads report to one recorder; after the server
stops, `Capture.evidence` is the immutable record.
"""

import http.server
import itertools
import json
import queue
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
    outcome: str            # "captured" | "forwarded" | "refused" | "ws-refused" | "unreadable" | "incomplete"
    status: int | None = None


@dataclass(frozen=True)
class Evidence:
    """A detached snapshot: requests are kept as JSON text and parsed afresh on every read."""

    requests_json: tuple[str, ...]
    traffic: tuple[Traffic, ...]

    @classmethod
    def of(cls, requests, traffic) -> "Evidence":
        return cls(tuple(json.dumps(r) for r in requests), tuple(traffic))

    @property
    def requests(self) -> tuple[dict, ...]:
        return tuple(json.loads(r) for r in self.requests_json)


class _Message(NamedTuple):
    traffic: Traffic
    sequence: int = 0
    request: dict | None = None


class _Recorder:
    """Handler threads only post messages; the evidence is assembled once, by the owner, after they finish.

    A request's sequence number (which decides the scripted reply) comes from an atomic counter.
    """

    def __init__(self):
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()
        self._sequence = itertools.count(1)

    def request(self, req: dict, path: str) -> int:
        n = next(self._sequence)
        self._inbox.put(_Message(Traffic("POST", path, "captured"), n, req))
        return n

    def traffic(self, item: Traffic) -> None:
        self._inbox.put(_Message(item))

    def finish(self) -> Evidence:
        messages = []
        while not self._inbox.empty():
            messages.append(self._inbox.get())
        requests = sorted((m for m in messages if m.request is not None), key=lambda m: m.sequence)
        return Evidence.of([m.request for m in requests], [m.traffic for m in messages])


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


class _Server(http.server.ThreadingHTTPServer):
    """Handler threads are joined on close, so the evidence snapshot is taken after every handler finished."""

    daemon_threads = False
    block_on_close = True


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
            """A connection dropped once a request is recorded is routine (the CLI hangs up on fetches it no longer
            needs) and is ignored; one dropped after the request line but before recording is evidence."""

            protocol_version = "HTTP/1.1"
            recorded = False

            def handle_one_request(self):
                self.command, self.recorded = None, False
                super().handle_one_request()

            def handle(self):
                try:
                    super().handle()
                except ConnectionError:
                    if self.command and not self.recorded:
                        rec.traffic(Traffic(self.command, (self.path or "").split("?")[0], "incomplete"))

            def _note(self, item: Traffic):
                rec.traffic(item)
                self.recorded = True

            def _send(self, code, body=b"", ctype="application/json"):
                self.send_response(code)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?")[0]
                if self.headers.get("Upgrade"):
                    self._note(Traffic("GET", path, "ws-refused"))
                    return self._send(404)
                upstream = next((base + self.path[len(pre):] for pre, base in CODEX_UPSTREAM.items()
                                 if self.path.startswith(pre)), None)
                if not (cap.forward and upstream):
                    self._note(Traffic("GET", path, "refused"))
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
                self._note(Traffic("GET", path, "forwarded", code))
                self._send(code, body, ctype)

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                path = self.path.split("?")[0]
                if path.endswith("/responses") or (path.endswith("/messages") and "count_tokens" not in path):
                    try:
                        req = json.loads(body)
                    except ValueError:
                        self._note(Traffic("POST", path, "unreadable"))
                        return self._send(400)
                    n = rec.request(req if isinstance(req, dict) else {"_unexpected": req}, path)
                    self.recorded = True
                    stream = (responses_stream(n, cap.tool_item) if cap.lineage == "codex"
                              else messages_stream(n, req.get("model", "") if isinstance(req, dict) else "",
                                                   cap.tool_use))
                    return self._send(200, stream, "text/event-stream")
                if path.endswith("count_tokens"):
                    self.recorded = True
                    return self._send(200, b'{"input_tokens": 1}')
                self._note(Traffic("POST", path, "refused"))
                self._send(404)

            def log_message(self, *args):
                pass

        self._server = _Server(("127.0.0.1", 0), Handler)
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
    supplied = request.get("tools", [])
    top = list(supplied) if isinstance(supplied, list) else ["?"]
    for item in request.get("input") if isinstance(request.get("input"), list) else []:
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            top += item.get("tools") if isinstance(item.get("tools", []), list) and "tools" in item else ["?"]
    names: list[str] = []

    def walk(tools, prefix):
        for t in tools:
            if not isinstance(t, dict):
                names.append(f"{prefix}?")
                continue
            name = t.get("name") or t.get("type")
            if isinstance(t.get("tools"), list):
                walk(t["tools"], f"{prefix}{name}.")
            else:
                names.append(f"{prefix}{name}")

    walk(top, "")
    return names


def claude_tools(request: dict) -> list[str]:
    tools = request.get("tools", [])
    return [str(t.get("name")) if isinstance(t, dict) else "?" for t in tools] if isinstance(tools, list) else ["?"]


_MISSING = object()


def tool_output(requests: tuple[dict, ...], call_id: str):
    """The tool output the CLI returned for `call_id`, exactly as sent; `_MISSING` if absent."""
    for req in requests[1:]:
        for item in req.get("input") if isinstance(req.get("input"), list) else []:
            is_output = isinstance(item, dict) and str(item.get("type", "")).endswith("_output")
            if is_output and item.get("call_id") == call_id:
                return item.get("output")
        for msg in req.get("messages") if isinstance(req.get("messages"), list) else []:
            content = msg.get("content") if isinstance(msg, dict) else None
            for block in content if isinstance(content, list) else []:
                is_result = isinstance(block, dict) and block.get("type") == "tool_result"
                if is_result and block.get("tool_use_id") == call_id:
                    return block.get("content")
    return _MISSING


def tool_text(requests: tuple[dict, ...], call_id: str) -> str:
    """The same output flattened to text, for canary searches."""
    out = tool_output(requests, call_id)
    return "" if out is _MISSING else json.dumps(out, ensure_ascii=False) if not isinstance(out, str) else out


def request_text(requests: tuple[dict, ...]) -> str:
    """Everything the CLI sent, as one string, for canary checks."""
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in requests)
