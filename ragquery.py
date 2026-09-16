"""docs-RAG 查詢 CLI（供本機開發流程經 ssh 呼叫；唯讀）。

用法: printf '%s\n' "<query>" | .venv/bin/python ragquery.py [-k N]
輸出: 每筆一行 "[path] (seq N) text[:400]"；末行附語料 metadata（corpus freshness）。
"""
from __future__ import annotations

import argparse
import sys

from searchlib import corpus_stats, log_query, retrieve


def main() -> int:
    parser = argparse.ArgumentParser(description="docs RAG query (read-only)")
    parser.add_argument("-k", type=int, default=4)
    args = parser.parse_args()
    if args.k < 1:
        parser.error("k 須為正整數（>= 1）")
    query = sys.stdin.read().strip()
    if not query:
        print("ragquery: 空查詢（stdin 需一行查詢字串）", file=sys.stderr)
        return 2
    for row in retrieve(query, k=args.k, caller="cli"):
        text = " ".join(str(row.get("text", "")).split())
        print(f"[{row.get('path')}] (seq {row.get('seq')}) {text[:400]}")
    log_query("corpus_status", caller="cli")
    stats = corpus_stats()
    print(
        "-- corpus: {files} files / {chunks} chunks / head={head} / synced_at={synced} / dirty={dirty}".format(
            files=stats.get("files"),
            chunks=stats.get("chunks"),
            head=stats.get("corpus_head"),
            synced=stats.get("synced_at"),
            dirty=stats.get("dirty"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
