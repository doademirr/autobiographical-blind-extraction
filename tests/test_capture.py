import json
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


class CaptureServerTest(unittest.TestCase):
    def test_codex_scripted_call_then_message_and_result_lookup(self):
        item = {"type": "function_call", "id": "fc", "call_id": "call_w", "name": "wait", "arguments": "{}"}
        with capture.Capture("codex", tool_item=item) as cap:
            first = _events(_post(f"{cap.base_url}/v1/responses", {"input": []}))
            second = _events(_post(f"{cap.base_url}/v1/responses", {"input": [
                {"type": "function_call_output", "call_id": "call_w", "output": "code-mode host is disabled"}]}))
        self.assertEqual(first[1]["item"]["call_id"], "call_w")
        self.assertEqual(second[1]["item"]["type"], "message")
        self.assertEqual(capture.tool_result(cap.requests, "call_w"), "code-mode host is disabled")
        self.assertIsNone(capture.tool_result(cap.requests, "other"))

    def test_claude_scripted_tool_use_and_result_lookup(self):
        with capture.Capture("claude", tool_use=("Read", {"file_path": "/x"})) as cap:
            first = _events(_post(f"{cap.base_url}/v1/messages", {"model": "m", "messages": []}))
            _post(f"{cap.base_url}/v1/messages", {"model": "m", "messages": [{"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_abx", "content": [{"type": "text", "text": "C"}]}]}]})
        self.assertEqual(first[1]["content_block"]["name"], "Read")
        self.assertEqual(capture.tool_result(cap.requests, "toolu_abx"), "C")

    def test_unforwarded_reads_and_other_posts_are_refused_and_logged(self):
        with capture.Capture("codex") as cap:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                _post(f"{cap.base_url}/backend-api/ps/mcp", {})
            cm.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(f"{cap.base_url}/codex-up/models", timeout=10)
            cm.exception.close()
        self.assertEqual([t["outcome"] for t in cap.traffic], ["refused", "refused"])

    def test_tool_list_walks_namespaces(self):
        request = {"input": [{"type": "additional_tools", "tools": [
            {"type": "namespace", "name": "functions", "tools": [{"type": "custom", "name": "exec"},
                                                                 {"type": "function", "name": "wait"}]},
            {"type": "namespace", "name": "clock", "tools": [{"type": "function", "name": "sleep"}]}]}]}
        self.assertEqual(capture.codex_tools(request), ["functions.exec", "functions.wait", "clock.sleep"])


if __name__ == "__main__":
    unittest.main()
