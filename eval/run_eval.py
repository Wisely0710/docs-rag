#!/usr/bin/env python3
"""Retrieval-quality evaluation harness for docs-rag.

Measures the shipped retrieval path end to end — `indexer.py` builds/refreshes the
index, then `searchlib.retrieve` answers a labelled query set — and reports
recall@k, MRR and query latency plus a per-query table for error analysis.

Golden file format (JSONL, one object per line):

    {"id": "own-1", "query": "...", "expected": "docs/book/ch04-01-what-is-ownership.md",
     "family": "en", "evidence": "ownership"}

`expected` is a corpus-relative document path; `family` groups rows (e.g. language)
and `evidence` is an optional string that must occur in the expected document — a
cheap sanity check that the label points at a document that actually mentions it.

Usage:

    python eval/run_eval.py --rag-dir eval/.work --corpus book \\
        --golden eval/golden/book.jsonl --k 10 --report eval/report-book.md

The harness sets RAG_DIR / RAG_CORPUS / RAG_EMBED_BACKEND in the environment before
importing the service modules, so one process owns exactly one corpus (the service
imports its config at module load; this is the same contract as tests/conftest.py).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEXER = REPO_ROOT / "indexer.py"
RECALL_AT = (1, 3, 5, 10)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="docs-rag retrieval evaluation")
    parser.add_argument("--rag-dir", required=True, help="RAG_DIR holding corpora.json and the index")
    parser.add_argument("--corpus", required=True, help="corpus name as declared in corpora.json")
    parser.add_argument("--golden", required=True, help="golden query set (JSONL)")
    parser.add_argument("--k", type=int, default=10, help="results per query (1-10; the service clamps)")
    parser.add_argument(
        "--backend",
        choices=("stub", "lmstudio", "none"),
        default="none",
        help="override RAG_EMBED_BACKEND for this run (default: the environment's)",
    )
    parser.add_argument("--report", help="write a markdown report here")
    parser.add_argument("--json", help="write raw results here")
    parser.add_argument("--no-reindex", action="store_true", help="skip the indexer (reuse the existing index)")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="delete the index before indexing (required when switching embedding backends)",
    )
    parser.add_argument("--min-recall", type=float, help="exit non-zero unless recall@k is at least this")
    return parser.parse_args(argv)


def configure_env(args: argparse.Namespace) -> dict[str, str]:
    """Point the service modules at this run's corpus (their config is read at import time)."""
    env = dict(os.environ)
    env["RAG_DIR"] = str(Path(args.rag_dir).resolve())
    env["RAG_CORPUS"] = args.corpus
    env.pop("RAG_CORPUS_DIR", None)  # the corpus_dir declared in corpora.json must win
    if args.backend != "none":
        env["RAG_EMBED_BACKEND"] = args.backend
    for key in ("RAG_DIR", "RAG_CORPUS", "RAG_EMBED_BACKEND"):
        if key in env:
            os.environ[key] = env[key]
    os.environ.pop("RAG_CORPUS_DIR", None)
    return env


def data_dir_for(rag_dir: Path, corpus: str) -> Path:
    """The corpus's data_dir, as declared in corpora.json (falls back to data-<corpus>)."""
    try:
        spec = json.loads((rag_dir / "corpora.json").read_text(encoding="utf-8"))[corpus]
        return rag_dir / str(spec["data_dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return rag_dir / f"data-{corpus}"


def run_indexer(env: dict[str, str]) -> str:
    proc = subprocess.run(
        [sys.executable, str(INDEXER)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(f"indexer failed with exit code {proc.returncode}")
    return proc.stdout.strip()


def load_golden(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise SystemExit(f"{path}:{lineno}: not valid JSON ({exc})") from exc
        for key in ("id", "query", "expected"):
            if not row.get(key):
                raise SystemExit(f"{path}:{lineno}: missing {key!r}")
        if row["id"] in seen:
            raise SystemExit(f"{path}:{lineno}: duplicate id {row['id']!r}")
        seen.add(row["id"])
        row.setdefault("family", "all")
        rows.append(row)
    if not rows:
        raise SystemExit(f"{path}: no golden rows")
    return rows


def check_labels(rows: list[dict[str, Any]], corpus_dir: Path) -> list[str]:
    """Return warnings for labels the corpus itself does not support."""
    warnings: list[str] = []
    for row in rows:
        target = corpus_dir / row["expected"]
        if not target.is_file():
            warnings.append(f"{row['id']}: expected document not in corpus: {row['expected']}")
            continue
        evidence = row.get("evidence")
        if evidence and evidence.lower() not in target.read_text(encoding="utf-8", errors="replace").lower():
            warnings.append(f"{row['id']}: evidence {evidence!r} not found in {row['expected']}")
    return warnings


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def evaluate(rows: list[dict[str, Any]], k: int) -> dict[str, Any]:
    import searchlib  # imported here: the module reads RAG_* config at import time

    results: list[dict[str, Any]] = []
    for row in rows:
        started = time.perf_counter()
        hits = searchlib.retrieve(row["query"], k=k, caller="eval")
        elapsed_ms = (time.perf_counter() - started) * 1000
        paths: list[str] = []
        for hit in hits:
            if hit["path"] not in paths:
                paths.append(hit["path"])
        rank = paths.index(row["expected"]) + 1 if row["expected"] in paths else 0
        results.append(
            {
                "id": row["id"],
                "family": row["family"],
                "query": row["query"],
                "expected": row["expected"],
                "rank": rank,
                "top1": paths[0] if paths else "",
                "ms": round(elapsed_ms, 1),
                "hits": len(paths),
            }
        )
        marker = "hit" if rank else "MISS"
        print(f"[{row['id']}] {marker:4} rank={rank or '-'} {elapsed_ms:6.1f}ms  {row['query'][:70]}")

    ranks = [r["rank"] for r in results]
    metrics: dict[str, Any] = {
        "queries": len(results),
        "k": k,
        "recall": {f"@{n}": round(sum(1 for rank in ranks if 0 < rank <= n) / len(ranks), 4) for n in RECALL_AT},
        "mrr": round(sum(1.0 / rank for rank in ranks if rank) / len(ranks), 4),
        "latency_ms": {
            "p50": round(percentile([r["ms"] for r in results], 0.50), 1),
            "p95": round(percentile([r["ms"] for r in results], 0.95), 1),
        },
    }
    return {"metrics": metrics, "results": results}


def family_metrics(results: list[dict[str, Any]], k: int) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for family in sorted({r["family"] for r in results}):
        rows = [r for r in results if r["family"] == family]
        ranks = [r["rank"] for r in rows]
        out[family] = {
            "queries": len(rows),
            "recall@1": round(sum(1 for rank in ranks if 0 < rank <= 1) / len(ranks), 4),
            "recall@3": round(sum(1 for rank in ranks if 0 < rank <= 3) / len(ranks), 4),
            "recall@5": round(sum(1 for rank in ranks if 0 < rank <= 5) / len(ranks), 4),
            "mrr": round(sum(1.0 / rank for rank in ranks if rank) / len(ranks), 4),
        }
    return out


def display_location(rag_dir: Path) -> str:
    """A publishable description of where the corpus lives (no absolute user paths)."""
    try:
        return str(rag_dir.relative_to(REPO_ROOT))
    except ValueError:
        return f"<RAG_DIR>/{rag_dir.name}"


def markdown_report(
    *,
    golden: Path,
    corpus: str,
    location: str,
    backend: str,
    model: str,
    index_log: str,
    stats: dict[str, Any],
    payload: dict[str, Any],
    k: int,
) -> str:
    metrics = payload["metrics"]
    results = payload["results"]
    lines = [
        "# Retrieval evaluation — `book` corpus",
        "",
        f"- Golden set: `{golden}` ({metrics['queries']} labelled queries, k={k})",
        (
            f"- Corpus: `{corpus}` under `{location}` — {stats.get('files')} files / {stats.get('chunks')} chunks "
            f"(head {stats.get('corpus_head') or 'unknown'})"
        ),
        f"- Embeddings: {model} ({backend} backend), 768-d; ranking: vector KNN + FTS5 trigram fused with RRF (k=60)",
        "",
        "## Summary",
        "",
        "| metric | value |",
        "|---|---|",
        f"| recall@1 | {metrics['recall']['@1']} |",
        f"| recall@3 | {metrics['recall']['@3']} |",
        f"| recall@5 | {metrics['recall']['@5']} |",
        f"| MRR@{k} | {metrics['mrr']} |",
        f"| latency p50 (ms) | {metrics['latency_ms']['p50']} |",
        f"| latency p95 (ms) | {metrics['latency_ms']['p95']} |",
        "",
        "By family:",
        "",
        "| family | queries | recall@1 | recall@3 | recall@5 | MRR |",
        "|---|---|---|---|---|---|",
    ]
    for family, data in payload["by_family"].items():
        lines.append(
            f"| {family} | {data['queries']} | {data['recall@1']} | {data['recall@3']} | "
            f"{data['recall@5']} | {data['mrr']} |"
        )
    lines += [
        "",
        "## Per query",
        "",
        "| id | family | rank | top-1 result | query |",
        "|---|---|---|---|---|",
    ]
    for row in results:
        rank = row["rank"] or "miss"
        lines.append(f"| {row['id']} | {row['family']} | {rank} | `{row['top1']}` | {row['query']} |")
    misses = [r for r in results if not r["rank"]]
    lines += ["", "## Misses", ""]
    if misses:
        for row in misses:
            lines.append(
                f"- `{row['id']}` ({row['family']}): expected `{row['expected']}`, top-1 was `{row['top1']}` — {row['query']}"
            )
    else:
        lines.append("- none — every labelled query placed its document inside the top-k.")
    lines += ["", "## Indexer output", "", "```", index_log or "(skipped)", "```", ""]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    env = configure_env(args)
    rag_dir = Path(args.rag_dir).resolve()
    golden = Path(args.golden)

    index_log = ""
    if args.fresh:
        data_dir = data_dir_for(rag_dir, args.corpus)
        if data_dir.exists():
            import shutil

            shutil.rmtree(data_dir)
            print(f"removed {data_dir}")
    if not args.no_reindex:
        print("indexing…")
        index_log = run_indexer(env)

    rows = load_golden(golden)

    if str(REPO_ROOT) not in sys.path:  # the service modules live at the repo root
        sys.path.insert(0, str(REPO_ROOT))
    # Imported here on purpose: both modules read the RAG_* config at import time.
    import ragconfig
    import searchlib

    warnings = check_labels(rows, ragconfig.CORPUS_DIR)
    for warning in warnings:
        print(f"label warning: {warning}", file=sys.stderr)

    payload = evaluate(rows, k=max(1, min(args.k, 10)))
    payload["by_family"] = family_metrics(payload["results"], payload["metrics"]["k"])
    payload["corpus"] = {
        "name": args.corpus,
        "backend": args.backend if args.backend != "none" else os.environ.get("RAG_EMBED_BACKEND", "lmstudio"),
        "model": os.environ.get("EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5"),
        "stats": searchlib.corpus_stats(),
        "label_warnings": warnings,
    }

    metrics = payload["metrics"]
    print(
        f"\nrecall@1={metrics['recall']['@1']} recall@3={metrics['recall']['@3']} "
        f"recall@5={metrics['recall']['@5']} mrr={metrics['mrr']} "
        f"p50={metrics['latency_ms']['p50']}ms p95={metrics['latency_ms']['p95']}ms"
    )

    if args.json:
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"json: {args.json}")
    if args.report:
        report = markdown_report(
            golden=golden,
            corpus=args.corpus,
            location=display_location(rag_dir),
            backend=payload["corpus"]["backend"],
            model=payload["corpus"]["model"],
            index_log=index_log,
            stats=payload["corpus"]["stats"],
            payload=payload,
            k=metrics["k"],
        )
        Path(args.report).write_text(report, encoding="utf-8")
        print(f"report: {args.report}")

    if args.min_recall is not None:
        achieved = metrics["recall"][f"@{metrics['k']}"]
        if achieved < args.min_recall:
            print(
                f"FAIL: recall@{metrics['k']} {achieved} < --min-recall {args.min_recall}",
                file=sys.stderr,
            )
            return 1
        print(f"gate ok: recall@{metrics['k']} {achieved} >= {args.min_recall}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
