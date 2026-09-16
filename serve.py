#!/usr/bin/env python3
"""Per-project docs RAG MCP server (MCP SDK, streamable HTTP).

One instance per corpus (RAG_CORPUS / RAG_PORT / RAG_SERVER_NAME in env).
Tools:
  - retrieve(query, k=5): hybrid vector+FTS search over the project corpus
  - corpus_status(): index stats

Run: python3 serve.py   (env: RAG_HOST / RAG_PORT / RAG_CORPUS / RAG_SERVER_NAME,
                         .env for LM Studio key)
"""
from __future__ import annotations

import json
import os
import sqlite3

import ragconfig as cfg
import searchlib

# Presentation comes from the corpus config (ragconfig), with env overrides.
SERVER_NAME = cfg.SERVER_NAME
SYSTEM_NOTE = cfg.SYSTEM_NOTE


def format_results(results: list[dict], k: int) -> str:
    lines = [f"查詢回傳 {len(results)} 筆（要求 {k} 筆）。語料路徑皆相對 repo 根目錄。"]
    for i, r in enumerate(results, 1):
        lines.append(f"\n[{i}] score={r['score']} {r['path']} (seq {r['seq']})")
        lines.append(r["text"][:2500])
    return "\n".join(lines)


def main() -> None:
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer(SERVER_NAME)

    @mcp.tool(description=f"在「{SERVER_NAME}」文檔語料中做混合檢索（向量+FTS）。{SYSTEM_NOTE} 回傳依相關度排序的片段，含檔案路徑。")
    def retrieve(query: str, k: int = 5) -> str:
        try:
            results = searchlib.retrieve(query, k, caller="mcp")
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            searchlib.log_query("retrieve", caller="mcp", query=query, k=k, hits=-1)
            return f"檢索失敗：{exc!r}"
        return format_results(results, k)

    @mcp.tool(description="回傳語料索引狀態：檔案數、chunk 數、最後索引時間與 corpus commit。")
    def corpus_status() -> str:
        searchlib.log_query("corpus_status", caller="mcp")
        return json.dumps(searchlib.corpus_stats(), ensure_ascii=False)

    transport = os.environ.get("RAG_MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "sse":
        mcp.run(transport="sse", host=cfg.HOST, port=cfg.PORT)
    elif transport == "streamable-http":
        mcp.run(transport="streamable-http", host=cfg.HOST, port=cfg.PORT)
    else:
        raise ValueError(f"unsupported RAG_MCP_TRANSPORT: {transport!r}")


if __name__ == "__main__":
    main()
