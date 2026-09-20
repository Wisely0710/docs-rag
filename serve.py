#!/usr/bin/env python3
"""Per-project docs RAG MCP server (MCP SDK, streamable HTTP or stdio).

One instance per corpus (RAG_CORPUS / RAG_PORT / RAG_SERVER_NAME in env).
Tools:
  - retrieve(query, k=5): hybrid vector+FTS search over the project corpus
  - corpus_status(): index stats

Run: python3 serve.py   (env: RAG_HOST / RAG_PORT / RAG_CORPUS / RAG_SERVER_NAME,
                         RAG_AUTH_TOKEN for any non-loopback bind; .env for the model key)

Exposure policy (netguard.py): loopback by default, a bearer token is mandatory for any
other host, and Host/Origin validation is on for every HTTP transport. Tool calls are
traced by the retrieval layer and by this module (tracing.py), so a deployment can be
replayed and metered from `<logs>/traces-<corpus>.jsonl`.
"""
from __future__ import annotations

import json
import os
import sqlite3

import netguard
import ragconfig as cfg
import searchlib
import tracing

# Presentation comes from the corpus config (ragconfig), with env overrides.
SERVER_NAME = cfg.SERVER_NAME
SYSTEM_NOTE = cfg.SYSTEM_NOTE


def format_results(results: list[dict], k: int) -> str:
    lines = [f"查詢回傳 {len(results)} 筆（要求 {k} 筆）。語料路徑皆相對 repo 根目錄。"]
    for i, r in enumerate(results, 1):
        lines.append(f"\n[{i}] score={r['score']} {r['path']} (seq {r['seq']})")
        lines.append(r["text"][:2500])
    return "\n".join(lines)


def build_server():  # type: ignore[no-untyped-def]
    """The MCP server with its tool surface (imported lazily: stdio runs need no HTTP)."""
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer(SERVER_NAME)

    @mcp.tool(description=f"在「{SERVER_NAME}」文檔語料中做混合檢索（向量+FTS）。{SYSTEM_NOTE} 回傳依相關度排序的片段，含檔案路徑。")
    def retrieve(query: str, k: int = 5) -> str:
        try:
            results = searchlib.retrieve(query, k, caller="mcp")
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            searchlib.log_query("retrieve", caller="mcp", query=query, k=k, hits=-1)
            tracing.record(
                "tool",
                {
                    "docs_rag.tool": "retrieve",
                    "docs_rag.caller": "mcp",
                    "docs_rag.error": True,
                    "docs_rag.error_type": type(exc).__name__,
                },
            )
            return f"檢索失敗：{exc!r}"
        return format_results(results, k)

    @mcp.tool(description="回傳語料索引狀態：檔案數、chunk 數、最後索引時間與 corpus commit。")
    def corpus_status() -> str:
        searchlib.log_query("corpus_status", caller="mcp")
        return json.dumps(searchlib.corpus_stats(), ensure_ascii=False)

    return mcp


def build_http_app(mcp, transport: str, host: str, port: int, token: str):  # type: ignore[no-untyped-def]
    """HTTP app for ``transport`` with Host/Origin validation and the token guard.

    The guard wraps the whole MCP app, so an unauthenticated request never reaches the
    session manager (no tool listing, no session).
    """
    settings = netguard.security_settings(host, port)
    app = mcp.sse_app(transport_security=settings, host=host) if transport == "sse" else mcp.streamable_http_app(
        transport_security=settings, host=host
    )
    return netguard.BearerTokenGuard(app, token) if token else app


def main() -> None:
    host, token = netguard.resolve_binding()
    port = cfg.PORT
    transport = os.environ.get("RAG_MCP_TRANSPORT", "streamable-http")
    tracing.record(
        "deployment",
        {
            "docs_rag.transport": transport,
            "docs_rag.host": host,
            "docs_rag.port": port,
            "docs_rag.auth": bool(token),
            "docs_rag.embed_backend": cfg.EMBED_BACKEND,
        },
    )
    if transport == "stdio":
        build_server().run(transport="stdio")
        return
    if transport not in {"sse", "streamable-http"}:
        raise ValueError(f"unsupported RAG_MCP_TRANSPORT: {transport!r}")
    app = build_http_app(build_server(), transport, host, port, token)
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
