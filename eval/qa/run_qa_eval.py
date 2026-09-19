#!/usr/bin/env python3
"""Answer-quality evaluation harness for docs-rag (LLM-as-judge).

Measures the QA layer end to end: the real `indexer.py` builds/refreshes the index, the
real `searchlib.retrieve` supplies excerpts, `qa.answer` produces a cited answer, and one
or two judges (LLM-as-judge) score it against a reference answer. Reports accuracy,
abstention behaviour, citation validity, judge agreement and a per-question table for
error analysis.

Golden file format (JSONL, one object per line):

    {"id": "x402-1", "family": "en", "question": "...", "reference": "...",
     "expected_docs": ["docs/x402-agent-payments/verifier/README.md"], "evidence": "fail closed"}

    {"id": "out-1", "family": "en", "question": "...", "unanswerable": true}

`reference` is the answer the judges compare the candidate against and `expected_docs` are
the corpus documents that should be retrieved (the retrieval hit rate is reported next to
accuracy). `unanswerable: true` rows deliberately ask something outside the corpus — the
correct behaviour is abstention (NOT_IN_CORPUS), so they carry no reference.

Usage:

    python eval/qa/run_qa_eval.py --rag-dir eval/qa/.work --corpus portfolio \\
        --golden eval/qa/golden/portfolio.jsonl --k 6 \\
        --answer-backend deepseek --judge-backend deepseek --judge-model deepseek-v4-pro \\
        --judge2-backend lmstudio --judge2-model qwen/qwen3.5-9b \\
        --report eval/qa/report-portfolio.md --json eval/qa/report-portfolio.json

The harness sets RAG_DIR / RAG_CORPUS / RAG_EMBED_BACKEND in the environment before
importing the service modules, so one process owns exactly one corpus — the same contract
as eval/run_eval.py (and tests/conftest.py).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.evalutil import load_jsonl, percentile


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="docs-rag answer-quality evaluation")
    parser.add_argument("--rag-dir", required=True, help="RAG_DIR holding corpora.json and the index")
    parser.add_argument("--corpus", required=True, help="corpus name as declared in corpora.json")
    parser.add_argument("--golden", required=True, help="golden QA set (JSONL)")
    parser.add_argument("--k", type=int, default=6, help="excerpts retrieved per question (1-10; the service clamps)")
    parser.add_argument(
        "--embed-backend",
        choices=("stub", "lmstudio", "none"),
        default="none",
        help="override RAG_EMBED_BACKEND for this run (default: the environment's)",
    )
    parser.add_argument(
        "--answer-backend",
        choices=("stub", "deepseek", "lmstudio"),
        default="deepseek",
        help="chat backend answering the questions",
    )
    parser.add_argument("--answer-model", help="answering model (defaults: deepseek-flash, stub)")
    parser.add_argument("--answer-max-tokens", type=int, default=800, help="answer completion cap (default 800)")
    parser.add_argument(
        "--judge-backend",
        choices=("stub", "deepseek", "lmstudio"),
        default="deepseek",
        help="primary judge backend",
    )
    parser.add_argument("--judge-model", help="primary judge model (default: the backend's default)")
    parser.add_argument(
        "--judge2-backend",
        choices=("stub", "deepseek", "lmstudio"),
        help="optional second judge, for cross-family agreement",
    )
    parser.add_argument("--judge2-model", help="second judge model (required when --judge2-backend is set)")
    parser.add_argument(
        "--judge-max-tokens",
        type=int,
        default=2000,
        help="primary judge completion cap (reasoning judges emit reasoning tokens first)",
    )
    parser.add_argument(
        "--judge2-max-tokens",
        type=int,
        default=2500,
        help="second judge completion cap (reasoning models emit reasoning tokens first)",
    )
    parser.add_argument("--report", help="write a markdown report here")
    parser.add_argument("--json", help="write raw results here")
    parser.add_argument("--spotcheck", help="JSON file with human spot-check rows to embed in the report")
    parser.add_argument(
        "--render-from",
        help="render the report from a previous --json payload instead of running models "
        "(used to attach a spot-check after human review, without re-running)",
    )
    parser.add_argument("--no-reindex", action="store_true", help="skip the indexer (reuse the existing index)")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="delete the index before indexing (required when switching embedding backends)",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        help="exit non-zero unless the primary judge's strict accuracy on answerable rows reaches this",
    )
    parser.add_argument(
        "--min-citation-validity",
        type=float,
        help="exit non-zero unless this share of cited paths exists in the corpus",
    )
    return parser.parse_args(argv)


def load_golden_qa(path: Path) -> list[dict[str, Any]]:
    rows = load_jsonl(path, required=("id", "question"))
    for row in rows:
        row["unanswerable"] = bool(row.get("unanswerable"))
        if row["unanswerable"]:
            row.setdefault("expected_docs", [])
            row.setdefault("reference", "")
            continue
        if not row.get("reference") or not row.get("expected_docs"):
            raise SystemExit(
                f"{path}: row {row['id']!r} needs 'reference' and 'expected_docs' (or \"unanswerable\": true)"
            )
        if not isinstance(row["expected_docs"], list):
            raise SystemExit(f"{path}: row {row['id']!r}: expected_docs must be a list of corpus paths")
    return rows


def check_labels(rows: list[dict[str, Any]], corpus_dir: Path) -> list[str]:
    """Warnings for labels the corpus itself does not support."""
    warnings: list[str] = []
    for row in rows:
        if row["unanswerable"]:
            continue
        texts: list[str] = []
        for doc in row["expected_docs"]:
            target = corpus_dir / str(doc)
            if not target.is_file():
                warnings.append(f"{row['id']}: expected document not in corpus: {doc}")
                continue
            texts.append(target.read_text(encoding="utf-8", errors="replace").lower())
        evidence = row.get("evidence")
        if evidence and texts and not any(str(evidence).lower() in text for text in texts):
            warnings.append(f"{row['id']}: evidence {evidence!r} not found in any expected document")
    return warnings


def fixed_retriever(hits: list[dict[str, Any]]) -> Callable[[str, int], list[dict[str, Any]]]:
    """A retriever that returns the excerpts already retrieved for this row (no second query)."""
    return lambda _question, _k: hits


def safe_answer(
    question: str,
    hits: list[dict[str, Any]],
    *,
    client: Any,
    k: int,
    max_tokens: int,
) -> tuple[Any | None, str | None]:
    """Answer one question; a chat failure is recorded, never fatal for the whole run.

    One truncated or empty reply from a serving endpoint must not throw away the other
    35 rows — the row is marked as an answer failure and excluded from the accuracy
    denominators (and counted in `answer_failures`).
    """
    from qa.answer import answer_question
    from qa.llm import ChatError

    try:
        answer = answer_question(
            question,
            retriever=fixed_retriever(hits),
            client=client,
            k=k,
            max_tokens=max_tokens,
        )
    except ChatError as exc:
        return None, f"chat failed: {exc}"
    return answer, None


def evaluate(rows: list[dict[str, Any]], *, args: argparse.Namespace) -> dict[str, Any]:
    import searchlib
    from corpus import iter_corpus_files, relpath_of
    from qa.answer import format_context
    from qa.judge import JudgeParseError, judge_answer
    from qa.llm import ChatError, make_client

    k = max(1, min(args.k, 10))
    answer_client = make_client(args.answer_backend, args.answer_model)
    judge_client = make_client(args.judge_backend, args.judge_model)
    judge2_client = make_client(args.judge2_backend, args.judge2_model) if args.judge2_backend else None
    models = {
        "answer": {"backend": answer_client.backend, "model": answer_client.model},
        "judge_primary": {"backend": judge_client.backend, "model": judge_client.model},
        "judge_secondary": (
            {"backend": judge2_client.backend, "model": judge2_client.model} if judge2_client else None
        ),
    }

    corpus_files = {relpath_of(path) for path in iter_corpus_files()}
    empty_judgment: dict[str, Any] = {
        "verdict": None,
        "rationale": "",
        "unsupported_claims": [],
        "error": None,
        "raw": "",
        "configured": False,
        "latency_ms": None,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }

    def judge_record(client: Any, record_args: dict[str, Any], configured: bool, max_tokens: int) -> dict[str, Any]:
        if not configured:
            return dict(empty_judgment)
        try:
            judgment = judge_answer(client=client, max_tokens=max_tokens, **record_args)
        except JudgeParseError as exc:
            return {
                **empty_judgment,
                "configured": True,
                "error": f"unparseable verdict: {exc}",
                "raw": exc.raw[:500],
            }
        except ChatError as exc:
            return {**empty_judgment, "configured": True, "error": f"chat failed: {exc}"}
        return {
            "verdict": judgment.verdict,
            "rationale": judgment.rationale,
            "unsupported_claims": judgment.unsupported_claims,
            "error": None,
            "configured": True,
            "latency_ms": judgment.reply.latency_ms,
            "prompt_tokens": judgment.reply.prompt_tokens,
            "completion_tokens": judgment.reply.completion_tokens,
        }

    results: list[dict[str, Any]] = []
    for row in rows:
        question = row["question"]
        hits = searchlib.retrieve(question, k=k, caller="qa")
        answer, answer_error = safe_answer(
            question,
            hits,
            client=answer_client,
            k=k,
            max_tokens=args.answer_max_tokens,
        )
        hit_paths = [hit["path"] for hit in hits]
        expected = [str(doc) for doc in row["expected_docs"]]
        retrieval_rank = next((index + 1 for index, path in enumerate(hit_paths) if path in expected), 0)
        retrieval_hit = retrieval_rank > 0 if expected else None
        judged = answer is not None
        judge_args = {
            "question": question,
            "candidate": answer.text if answer else "",
            "reference": str(row.get("reference", "")),
            "context": format_context(hits),
            "unanswerable": bool(row["unanswerable"]),
        }
        record = {
            "id": row["id"],
            "family": row["family"],
            "question": question,
            "unanswerable": bool(row["unanswerable"]),
            "reference": str(row.get("reference", "")),
            "expected_docs": expected,
            "retrieval_hit": retrieval_hit,
            "retrieval_rank": retrieval_rank,
            "retrieved": hit_paths,
            "answer": answer.text if answer else "",
            "answer_error": answer_error,
            "abstained": answer.abstained if answer else False,
            "citations": answer.citations if answer else [],
            "citations_valid": [path for path in answer.citations if path in corpus_files] if answer else [],
            "citations_retrieved": [path for path in answer.citations if path in hit_paths] if answer else [],
            "answer_latency_ms": answer.reply.latency_ms if answer else None,
            "answer_prompt_tokens": answer.reply.prompt_tokens if answer else 0,
            "answer_completion_tokens": answer.reply.completion_tokens if answer else 0,
            "judge1": judge_record(judge_client, judge_args, configured=judged, max_tokens=args.judge_max_tokens),
            "judge2": judge_record(
                judge2_client,
                judge_args,
                configured=judged and judge2_client is not None,
                max_tokens=args.judge2_max_tokens,
            ),
        }
        results.append(record)
        verdict1 = record["judge1"]["verdict"] or ("!" if answer_error else "?")
        verdict2 = record["judge2"]["verdict"] or "-"
        hit_marker = "hit " if retrieval_hit else ("miss" if expected else "n/a ")
        latency = f"{record['answer_latency_ms']:6.0f}ms" if record["answer_latency_ms"] is not None else "  FAILED"
        print(
            f"[{row['id']}] {record['family']:>3} {hit_marker} v1={verdict1:<9} v2={verdict2:<9} "
            f"{latency}  {question[:64]}"
        )

    return {"models": models, "results": results, "corpus_files": len(corpus_files)}


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa over two raters' labels (None when there is nothing to compare)."""
    total = len(pairs)
    if total == 0:
        return None
    labels = sorted({label for pair in pairs for label in pair})
    observed = sum(1 for first, second in pairs if first == second) / total
    expected = sum(
        (sum(1 for first, _ in pairs if first == label) / total)
        * (sum(1 for _, second in pairs if second == label) / total)
        for label in labels
    )
    if 1 - expected < 1e-12:
        return 1.0 if observed >= 1.0 else 0.0
    return round((observed - expected) / (1 - expected), 4)


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [row for row in results if not row["unanswerable"]]
    unanswerable = [row for row in results if row["unanswerable"]]

    def rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    def verdict(row: dict[str, Any], slot: str) -> str | None:
        return row[slot]["verdict"]

    judged1 = [row for row in answerable if verdict(row, "judge1")]
    judged2 = [row for row in answerable if verdict(row, "judge2")]
    judged_unanswerable = [row for row in unanswerable if verdict(row, "judge1")]
    paired: list[tuple[str, str]] = []
    for row in results:
        first, second = verdict(row, "judge1"), verdict(row, "judge2")
        if first and second:
            paired.append((first, second))

    citation_paths = sum(len(row["citations"]) for row in results)
    cited_rows = [row for row in results if row["citations"]]
    answer_latencies = [row["answer_latency_ms"] for row in results if row["answer_latency_ms"] is not None]

    return {
        "rows": len(results),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "answer_failures": sum(1 for row in results if row.get("answer_error")),
        "retrieval_hit_at_k": rate(sum(1 for row in answerable if row["retrieval_hit"]), len(answerable)),
        "answer_accuracy_primary": rate(
            sum(1 for row in judged1 if verdict(row, "judge1") == "correct"), len(judged1)
        ),
        "answer_accuracy_primary_lenient": rate(
            sum(1 for row in judged1 if verdict(row, "judge1") in ("correct", "partial")), len(judged1)
        ),
        "answer_accuracy_secondary": rate(
            sum(1 for row in judged2 if verdict(row, "judge2") == "correct"), len(judged2)
        ),
        "judge_agreement": {
            "rows": len(paired),
            "agreement": rate(sum(1 for first, second in paired if first == second), len(paired)),
            "kappa": cohen_kappa(paired),
        },
        "abstention_on_unanswerable_marker": rate(
            sum(1 for row in unanswerable if row["abstained"]), len(unanswerable)
        ),
        "abstention_on_unanswerable_primary": rate(
            sum(1 for row in judged_unanswerable if verdict(row, "judge1") == "correct"),
            len(judged_unanswerable),
        ),
        "over_abstention_answerable": rate(sum(1 for row in answerable if row["abstained"]), len(answerable)),
        "citations": {
            "answers_with_citations": rate(len(cited_rows), len(results)),
            "citation_paths_valid": rate(
                sum(len(row["citations_valid"]) for row in results), citation_paths
            ),
            "citation_paths_retrieved": rate(
                sum(len(row["citations_retrieved"]) for row in results), citation_paths
            ),
            "answers_all_citations_valid": rate(
                sum(1 for row in cited_rows if len(row["citations_valid"]) == len(row["citations"])),
                len(cited_rows),
            ),
        },
        "judge_failures": {
            "primary": sum(1 for row in answerable if row["judge1"]["error"]),
            "secondary": sum(1 for row in answerable if row["judge2"]["configured"] and row["judge2"]["error"]),
        },
        "latency_ms": {
            "answer_p50": round(percentile(answer_latencies, 0.50), 1),
            "answer_p95": round(percentile(answer_latencies, 0.95), 1),
        },
        "tokens": {
            "answer": {
                "prompt": sum(row["answer_prompt_tokens"] for row in results),
                "completion": sum(row["answer_completion_tokens"] for row in results),
            },
            "judge_primary": {
                "prompt": sum(row["judge1"]["prompt_tokens"] for row in results),
                "completion": sum(row["judge1"]["completion_tokens"] for row in results),
            },
            "judge_secondary": {
                "prompt": sum(row["judge2"]["prompt_tokens"] for row in results),
                "completion": sum(row["judge2"]["completion_tokens"] for row in results),
            },
        },
    }


def family_metrics(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for family in sorted({row["family"] for row in results}):
        rows = [row for row in results if row["family"] == family]
        answerable = [row for row in rows if not row["unanswerable"]]
        unanswerable = [row for row in rows if row["unanswerable"]]
        judged = [row for row in answerable if row["judge1"]["verdict"]]

        def rate(numerator: int, denominator: int) -> float | None:
            return round(numerator / denominator, 4) if denominator else None

        out[family] = {
            "rows": len(rows),
            "answerable": len(answerable),
            "retrieval_hit_at_k": rate(sum(1 for row in answerable if row["retrieval_hit"]), len(answerable)),
            "accuracy_primary": rate(sum(1 for row in judged if row["judge1"]["verdict"] == "correct"), len(judged)),
            "abstention_marker": rate(sum(1 for row in unanswerable if row["abstained"]), len(unanswerable)),
        }
    return out


def markdown_report(
    *,
    golden: Path,
    corpus: str,
    location: str,
    k: int,
    index_log: str,
    payload: dict[str, Any],
    spotcheck: dict[str, Any] | None,
) -> str:
    metrics = payload["metrics"]
    results = payload["results"]
    models = payload["models"]
    stats = payload["corpus"]["stats"]
    judge2 = models["judge_secondary"]
    citations = metrics["citations"]

    def fmt(value: Any) -> str:
        return "n/a" if value is None else str(value)

    tokens_row = (
        f"| tokens prompt+completion (answer) | "
        f"{metrics['tokens']['answer']['prompt']} + {metrics['tokens']['answer']['completion']} |"
    )
    judge_tokens = (
        f"| tokens prompt+completion (judge primary) | "
        f"{metrics['tokens']['judge_primary']['prompt']} + {metrics['tokens']['judge_primary']['completion']} |"
    )
    if judge2:
        judge_tokens += (
            f"\n| tokens prompt+completion (judge secondary) | "
            f"{metrics['tokens']['judge_secondary']['prompt']} + "
            f"{metrics['tokens']['judge_secondary']['completion']} |"
        )

    lines = [
        f"# Answer-quality evaluation — `{corpus}` corpus",
        "",
        (
            f"- Golden set: `{golden}` — {metrics['rows']} questions "
            f"({metrics['answerable']} answerable, {metrics['unanswerable']} unanswerable), k={k}"
        ),
        (
            f"- Corpus: `{corpus}` under `{location}` — {stats.get('files')} files / "
            f"{stats.get('chunks')} chunks (head {stats.get('corpus_head') or 'unknown'})"
        ),
        f"- Answerer: {models['answer']['backend']} / `{models['answer']['model']}`",
        (
            "- Judges: primary "
            f"{models['judge_primary']['backend']} / `{models['judge_primary']['model']}`"
            + (f"; secondary (cross-family) {judge2['backend']} / `{judge2['model']}`" if judge2 else "")
        ),
        (
            "- Sampling: one run at temperature 0, no averaging; reference answers were written from the "
            "cited documents — method and limits in [`README.md`](README.md)"
        ),
        "",
        "## Summary",
        "",
        "| metric | value |",
        "|---|---|",
        (
            f"| questions | {metrics['rows']} ({metrics['answerable']} answerable, "
            f"{metrics['unanswerable']} unanswerable) |"
        ),
        f"| answer failures (not judged) | {metrics['answer_failures']} |",
        f"| retrieval hit@{k} (answerable) | {fmt(metrics['retrieval_hit_at_k'])} |",
        f"| answer accuracy — primary (strict) | {fmt(metrics['answer_accuracy_primary'])} |",
        f"| answer accuracy — primary (correct+partial) | {fmt(metrics['answer_accuracy_primary_lenient'])} |",
        f"| answer accuracy — secondary (strict) | {fmt(metrics['answer_accuracy_secondary'])} |",
        (
            f"| judge agreement | {metrics['judge_agreement']['rows']} paired rows, "
            f"{fmt(metrics['judge_agreement']['agreement'])} agreement, kappa "
            f"{fmt(metrics['judge_agreement']['kappa'])} |"
        ),
        (
            f"| abstention on unanswerable (marker / primary judge) | "
            f"{fmt(metrics['abstention_on_unanswerable_marker'])} / "
            f"{fmt(metrics['abstention_on_unanswerable_primary'])} |"
        ),
        f"| over-abstention on answerable | {fmt(metrics['over_abstention_answerable'])} |",
        f"| answers with citations | {fmt(citations['answers_with_citations'])} |",
        f"| cited paths that exist in the corpus | {fmt(citations['citation_paths_valid'])} |",
        f"| cited paths that were retrieved | {fmt(citations['citation_paths_retrieved'])} |",
        f"| answers whose citations are all valid | {fmt(citations['answers_all_citations_valid'])} |",
        (
            f"| judge failures (primary / secondary) | "
            f"{metrics['judge_failures']['primary']} / {metrics['judge_failures']['secondary']} |"
        ),
        (
            f"| answer latency p50 / p95 (ms) | {metrics['latency_ms']['answer_p50']} / "
            f"{metrics['latency_ms']['answer_p95']} |"
        ),
        tokens_row,
        judge_tokens,
        "",
        "By family:",
        "",
        "| family | questions | answerable | retrieval hit@k | accuracy (primary) | abstention (unanswerable) |",
        "|---|---|---|---|---|---|",
    ]
    for family, data in payload["by_family"].items():
        lines.append(
            f"| {family} | {data['rows']} | {data['answerable']} | {fmt(data['retrieval_hit_at_k'])} | "
            f"{fmt(data['accuracy_primary'])} | {fmt(data['abstention_marker'])} |"
        )

    lines += [
        "",
        "## Per question",
        "",
        "| id | family | retrieval | abstained | verdict (primary) | verdict (secondary) | citations | question |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in results:
        retrieval = "n/a" if row["unanswerable"] else (str(row["retrieval_rank"]) if row["retrieval_rank"] else "miss")
        cited = ", ".join(f"`{path}`" for path in row["citations"]) or "—"
        lines.append(
            f"| {row['id']} | {row['family']} | {retrieval} | {'yes' if row['abstained'] else 'no'} | "
            f"{row['judge1']['verdict'] or '—'} | {row['judge2']['verdict'] or '—'} | {cited} | {row['question']} |"
        )

    failures = [
        row
        for row in results
        if not row["unanswerable"]
        and (row.get("answer_error") or row["judge1"]["verdict"] not in ("correct", None))
    ]
    lines += ["", "## Failures (primary judge)", ""]
    if failures:
        for row in failures:
            if row.get("answer_error"):
                lines.append(f"- `{row['id']}` ({row['family']}, **answer failed**): {row['question']}")
                lines.append(f"  - error: {row['answer_error']}")
                continue
            answer_excerpt = " ".join(row["answer"].split())[:240]
            lines.append(f"- `{row['id']}` ({row['family']}, **{row['judge1']['verdict']}**): {row['question']}")
            lines.append(f"  - answer: {answer_excerpt}")
            lines.append(f"  - rationale: {row['judge1']['rationale'] or '(none)'}")
            if row["judge1"]["unsupported_claims"]:
                lines.append(f"  - unsupported claims: {'; '.join(row['judge1']['unsupported_claims'])}")
            if row["judge1"]["error"]:
                lines.append(f"  - judge error: {row['judge1']['error']}")
    else:
        lines.append("- none — every answerable question was graded `correct` by the primary judge.")

    unanswerable_rows = [row for row in results if row["unanswerable"]]
    lines += [
        "",
        "## Unanswerable questions (abstention behaviour)",
        "",
        "| id | family | marker abstention | verdict (primary) | verdict (secondary) | answer |",
        "|---|---|---|---|---|---|",
    ]
    for row in unanswerable_rows:
        answer_excerpt = " ".join(row["answer"].split())[:160]
        if row.get("answer_error"):
            answer_excerpt = f"FAILED — {row['answer_error'][:120]}"
        lines.append(
            f"| {row['id']} | {row['family']} | {'yes' if row['abstained'] else 'no'} | "
            f"{row['judge1']['verdict'] or '—'} | {row['judge2']['verdict'] or '—'} | {answer_excerpt} |"
        )

    disagreements = [
        row
        for row in results
        if row["judge1"]["verdict"] and row["judge2"]["verdict"] and row["judge1"]["verdict"] != row["judge2"]["verdict"]
    ]
    lines += ["", "## Judge disagreements", ""]
    if disagreements:
        lines += [
            "| id | primary | secondary | primary rationale | secondary rationale |",
            "|---|---|---|---|---|",
        ]
        for row in disagreements:
            lines.append(
                f"| {row['id']} | {row['judge1']['verdict']} | {row['judge2']['verdict']} | "
                f"{row['judge1']['rationale']} | {row['judge2']['rationale']} |"
            )
    else:
        lines.append("- none.")

    if spotcheck:
        by_id = {row["id"]: row for row in results}
        lines += [
            "",
            "## Spot-check",
            "",
            str(spotcheck.get("note", "")),
            "",
            "| id | judge verdict (primary) | reviewer | note |",
            "|---|---|---|---|",
        ]
        for entry in spotcheck.get("rows", []):
            judged = by_id.get(entry["id"], {}).get("judge1", {}).get("verdict")
            lines.append(
                f"| {entry['id']} | {judged or '—'} | {entry.get('reviewer', '')} | {entry.get('note', '')} |"
            )

    if payload["corpus"].get("label_warnings"):
        lines += ["", "## Label warnings", ""]
        lines += [f"- {warning}" for warning in payload["corpus"]["label_warnings"]]

    lines += ["", "## Indexer output", "", "```", index_log or "(skipped)", "```", ""]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    from eval.evalutil import configure_env, data_dir_for, display_location, run_indexer, shorten_hashes

    rag_dir = Path(args.rag_dir).resolve()
    golden = Path(args.golden)
    k = max(1, min(args.k, 10))
    spotcheck = json.loads(Path(args.spotcheck).read_text(encoding="utf-8")) if args.spotcheck else None

    if args.render_from:
        payload = json.loads(Path(args.render_from).read_text(encoding="utf-8"))
        if args.report:
            report = markdown_report(
                golden=Path(payload.get("golden", str(golden))),
                corpus=args.corpus,
                location=payload["corpus"].get("location", display_location(rag_dir)),
                k=int(payload.get("k", k)),
                index_log=str(payload.get("index_log", "(not recorded)")),
                payload=payload,
                spotcheck=spotcheck,
            )
            Path(args.report).write_text(report, encoding="utf-8")
            print(f"report: {args.report}")
        return 0

    embed_backend = None if args.embed_backend == "none" else args.embed_backend
    env = configure_env(rag_dir=Path(args.rag_dir), corpus=args.corpus, embed_backend=embed_backend)

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

    rows = load_golden_qa(golden)

    import ragconfig
    import searchlib

    warnings = check_labels(rows, ragconfig.CORPUS_DIR)
    for warning in warnings:
        print(f"label warning: {warning}", file=sys.stderr)

    payload = evaluate(rows, args=args)
    payload["metrics"] = aggregate(payload["results"])
    payload["by_family"] = family_metrics(payload["results"])
    payload["golden"] = str(golden)
    payload["k"] = k
    payload["index_log"] = shorten_hashes(index_log)
    stats = searchlib.corpus_stats()
    if stats.get("corpus_head"):
        # Keep generated artefacts free of full 40-char hashes (secret scanners); the full
        # commit is recorded in the (uncommitted) .corpus_source.json by fetch_corpus.sh.
        stats["corpus_head"] = str(stats["corpus_head"])[:8]
    payload["corpus"] = {
        "name": args.corpus,
        "backend": args.embed_backend if args.embed_backend != "none" else os.environ.get("RAG_EMBED_BACKEND", "lmstudio"),
        "model": os.environ.get("EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5"),
        "location": display_location(rag_dir),
        "stats": stats,
        "label_warnings": warnings,
    }

    metrics = payload["metrics"]
    agreement = metrics["judge_agreement"]
    print(
        f"\naccuracy={metrics['answer_accuracy_primary']} (secondary "
        f"{metrics['answer_accuracy_secondary']}) agreement={agreement['agreement']} "
        f"kappa={agreement['kappa']} retrieval_hit@{k}={metrics['retrieval_hit_at_k']} "
        f"citation_valid={metrics['citations']['citation_paths_valid']} "
        f"p50={metrics['latency_ms']['answer_p50']}ms"
    )

    if args.json:
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"json: {args.json}")
    if args.report:
        report = markdown_report(
            golden=golden,
            corpus=args.corpus,
            location=payload["corpus"]["location"],
            k=k,
            index_log=payload["index_log"],
            payload=payload,
            spotcheck=spotcheck,
        )
        Path(args.report).write_text(report, encoding="utf-8")
        print(f"report: {args.report}")

    if args.min_accuracy is not None:
        achieved = metrics["answer_accuracy_primary"]
        if achieved is None or achieved < args.min_accuracy:
            print(f"FAIL: accuracy {achieved} < --min-accuracy {args.min_accuracy}", file=sys.stderr)
            return 1
        print(f"gate ok: accuracy {achieved} >= {args.min_accuracy}")
    if args.min_citation_validity is not None:
        achieved = metrics["citations"]["citation_paths_valid"]
        if achieved is None or achieved < args.min_citation_validity:
            print(
                f"FAIL: citation validity {achieved} < --min-citation-validity {args.min_citation_validity}",
                file=sys.stderr,
            )
            return 1
        print(f"gate ok: citation validity {achieved} >= {args.min_citation_validity}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
