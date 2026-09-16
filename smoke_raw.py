#!/usr/bin/env python3
"""Minimal stdlib MCP streamable-HTTP client (no deps) for cross-machine smoke.

Usage: python3 smoke_raw.py <url> <query>
Prints tool list then top results for the query. Works from machines without the
mcp SDK (e.g. the Intel Mac) to prove LAN reachability.
"""
from __future__ import annotations

import json
import sys
import urllib.request

HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _post(url: str, payload: dict, session_id: str | None) -> tuple[dict, str | None]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    if session_id:
        req.add_header("Mcp-Session-Id", session_id)
    with urllib.request.urlopen(req, timeout=60) as resp:
        sid = resp.headers.get("Mcp-Session-Id")
        raw = resp.read().decode("utf-8", "replace")
    # SSE framing: lines "event: message" + "data: {...}"
    last = None
    for line in raw.splitlines():
        if line.startswith("data:"):
            try:
                last = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                pass
    return last or json.loads(raw), sid


def rpc(url: str, method: str, params: dict, sid: str | None, req_id: int) -> tuple[dict, str | None]:
    return _post(url, {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}, sid)


def main() -> None:
    url, query = sys.argv[1], sys.argv[2]
    resp, sid = rpc(url, "initialize",
                    {"protocolVersion": "2025-03-26", "capabilities": {},
                     "clientInfo": {"name": "smoke-raw", "version": "0"}}, None, 1)
    assert "result" in resp, f"initialize failed: {resp}"
    print("server:", resp["result"]["serverInfo"], "protocol:", resp["result"].get("protocolVersion"))
    resp, sid = rpc(url, "tools/list", {}, sid, 2)
    tools = resp.get("result", {}).get("tools", [])
    print("tools:", [t["name"] for t in tools])
    resp, _ = rpc(url, "tools/call", {"name": "retrieve", "arguments": {"query": query, "k": 3}}, sid, 3)
    content = resp.get("result", {}).get("content", [])
    for block in content:
        if block.get("type") == "text":
            print(block["text"][:2000])


if __name__ == "__main__":
    main()
