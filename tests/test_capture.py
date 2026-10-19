import json
import socket
import struct
import time
import unittest
import urllib.error
import urllib.request

from abx import capture


def _post(url: str, body: dict) -> str:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode()


def _events(sse: str) -> list[dict]:
    return [json.loads(line[6:]) for line in sse.splitlines() if line.startswith("data: ")]


def _reset(port: int, payload: bytes) -> None:
    """Send `payload`, then abort the connection with a reset, as a CLI that hangs up does."""
    s = socket.create_connection(("127.0.0.1", port))
    s.sendall(payload)
    time.sleep(0.2)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    s.close()
    time.sleep(0.2)


class CaptureServerTest(unittest.TestCase):
    def test_a_request_dropped_before_capture_is_evidence_and_an_idle_reset_is_not(self):
        with capture.Capture("claude") as cap:
            _reset(cap.port, b"POST /v1/messages HTTP/1.1\r\nHost: x\r\nContent-Length: 1000\r\n\r\n{")
            _reset(cap.port, b"")
        self.assertEqual([(t.method, t.path, t.outcome) for t in cap.evidence.traffic],
                         [("POST", "/v1/messages", "incomplete")])

    def test_codex_scripted_call_then_message_and_result_lookup(self):
        item = {"type": "function_call", "id": "fc", "call_id": "call_w", "name": "wait", "arguments": "{}"}
        cap = capture.Capture("codex", tool_item=item)
        with cap:
            first = _events(_post(f"{cap.base_url}/v1/responses", {"input": []}))
            second = _events(_post(f"{cap.base_url}/v1/responses", {"input": [
                {"type": "function_call_output", "call_id": "call_w", "output": "code-mode host is disabled"}]}))
        self.assertEqual(first[1]["item"]["call_id"], "call_w")
        self.assertEqual(second[1]["item"]["type"], "message")
        self.assertEqual(capture.tool_output(cap.evidence.requests, "call_w"), "code-mode host is disabled")
        self.assertEqual(capture.tool_text(cap.evidence.requests, "other"), "")

    def test_claude_scripted_tool_use_and_result_lookup(self):
        cap = capture.Capture("claude", tool_use=("Read", {"file_path": "/x"}))
        with cap:
            first = _events(_post(f"{cap.base_url}/v1/messages", {"model": "m", "messages": []}))
            _post(f"{cap.base_url}/v1/messages", {"model": "m", "messages": [{"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_abx", "content": [{"type": "text", "text": "C"}]}]}]})
        self.assertEqual(first[1]["content_block"]["name"], "Read")
        self.assertEqual(capture.tool_output(cap.evidence.requests, "toolu_abx"), [{"type": "text", "text": "C"}])
        self.assertEqual(capture.tool_text(cap.evidence.requests, "toolu_abx"), '[{"type": "text", "text": "C"}]')

    def test_unforwarded_reads_and_other_posts_are_refused_and_logged(self):
        cap = capture.Capture("codex")
        with cap:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                _post(f"{cap.base_url}/backend-api/ps/mcp", {})
            cm.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(f"{cap.base_url}/codex-up/models", timeout=10)
            cm.exception.close()
        self.assertEqual([t.outcome for t in cap.evidence.traffic], ["refused", "refused"])

    def test_malformed_captured_requests_do_not_crash(self):
        weird = ({"input": None, "messages": None}, {"messages": [None, {"content": None}], "input": [None]})
        self.assertEqual(capture.tool_text(weird, "x"), "")
        self.assertEqual(capture.claude_tools({"tools": [None]}), ["?"])
        for falsy in ("", 0, False, {}):
            with self.subTest(falsy=falsy):
                self.assertEqual(capture.claude_tools({"tools": falsy}), ["?"])
                self.assertEqual(capture.codex_tools({"tools": falsy}), ["?"])
        self.assertEqual(capture.codex_tools({"input": [{"type": "additional_tools", "tools": [None]}]}), ["?"])

    def test_tool_list_walks_namespaces(self):
        request = {"input": [{"type": "additional_tools", "tools": [
            {"type": "namespace", "name": "functions", "tools": [{"type": "custom", "name": "exec"},
                                                                 {"type": "function", "name": "wait"}]},
            {"type": "namespace", "name": "clock", "tools": [{"type": "function", "name": "sleep"}]}]}]}
        self.assertEqual(capture.codex_tools(request), ["functions.exec", "functions.wait", "clock.sleep"])


if __name__ == "__main__":
    unittest.main()
