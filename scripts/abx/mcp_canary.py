"""A one-tool stdio MCP server whose only tool returns the canary given on its command line.

Qualification's positive control: an unlocked CLI that reaches it proves MCP access is
observable, so a locked CLI that cannot reach it proves something.
"""

import json
import sys

__all__ = ["main"]


def main() -> None:
    canary = sys.argv[1]
    for line in sys.stdin:
        msg = json.loads(line)
        mid, method = msg.get("id"), msg.get("method")
        if method == "initialize":
            result = {"protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "abxcanary", "version": "0"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "read_canary", "description": "Returns a value.",
                                 "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": canary}]}
        elif mid is None:
            continue
        else:
            result = {}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
