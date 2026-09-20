#!/usr/bin/env python3
"""Acceptance probe: run real retrieve calls over MCP streamable HTTP.

Usage: python probe.py <url> [queries-file]
  url           e.g. http://127.0.0.1:8765/mcp
  queries-file  optional, one query per line; otherwise a small generic set is used.

Set RAG_AUTH_TOKEN when the deployment serves a non-loopback bind (netguard.py requires
a bearer token there); with the token unset the probe talks to a loopback service.

Reports per-query top-1 path, latency percentiles, and index stats. Kept free of
corpus-specific queries so this file carries no project terminology: keep deployment
query lists in a separate, untracked file and pass it as the second argument.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import statistics
import sys
import time

DEFAULT_QUERIES = [
    "這個專案的主要目的是什麼",
    "目前的架構概觀",
    "有哪些已知的未完成事項",
    "如何在本機執行測試",
    "最近的重大變更是什麼",
]


def load_queries(path: str | None) -> list[str]:
    if not path:
        return DEFAULT_QUERIES
    lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    url = sys.argv[1]
    queries = load_queries(sys.argv[2] if len(sys.argv) > 2 else None)

    from mcp.client import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    token = os.environ.get("RAG_AUTH_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    import httpx2

    async with (
        httpx2.AsyncClient(headers=headers) as http_client,
        streamable_http_client(url, http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        print("tools:", [tool.name for tool in tools.tools])
        stats = await session.call_tool("corpus_status", {})
        print("corpus_status:", stats.content[0].text if stats.content else stats)

        lat = []
        for query in queries:
            t0 = time.perf_counter()
            res = await session.call_tool("retrieve", {"query": query, "k": 3})
            dt = (time.perf_counter() - t0) * 1000
            lat.append(dt)
            text = res.content[0].text if res.content else str(res)
            lines = text.splitlines()
            first = lines[2] if len(lines) > 2 else text[:120]
            print(f"{dt:7.1f}ms | {query[:28]:28s} | {first[:100]}")

        lat.sort()
        n = len(lat)
        print(
            f"\nqueries={n} p50={lat[n // 2]:.1f}ms p90={lat[int(n * 0.9) - 1]:.1f}ms "
            f"p95={lat[int(n * 0.95) - 1]:.1f}ms max={max(lat):.1f}ms mean={statistics.mean(lat):.1f}ms"
        )


if __name__ == "__main__":
    asyncio.run(main())
