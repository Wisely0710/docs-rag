"""Trace layer: content policy, OTel mapping, export, retention, meter and thresholds.

All offline: a trace file is a JSONL file, and the export path is deliberately
dependency-free, so every claim in the README's Observability section is asserted here
instead of being demonstrated by a live deployment.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib

import pytest

import ragconfig as cfg
import tracing

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_trace_dir_is_the_service_log_dir_not_the_checkout() -> None:
    assert tracing.trace_dir() == cfg.LOGS_DIR
    assert tracing.trace_dir() != REPO_ROOT / "logs"


def test_record_appends_one_json_object_per_call(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_CORPUS", "demo")
    row = tracing.record("retrieval", {"docs_rag.hits": 3}, directory=tmp_path, latency_ms=12.34)

    lines = (tmp_path / "traces-demo.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    stored = json.loads(lines[0])
    assert stored == row
    assert stored["kind"] == "retrieval"
    assert stored["docs_rag.corpus"] == "demo"
    assert stored["docs_rag.hits"] == 3
    assert stored["latency_ms"] == 12.3
    assert stored["ts"] and stored["trace_id"]


def test_content_is_hashed_unless_explicitly_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(tracing.CONTENT_ENV, raising=False)
    hidden = tracing.describe_content("secret question", field="query")
    assert "docs_rag.query_text" not in hidden
    assert hidden["docs_rag.query_sha256"] == hashlib.sha256(b"secret question").hexdigest()
    assert hidden["docs_rag.query_chars"] == len("secret question")

    monkeypatch.setenv(tracing.CONTENT_ENV, "1")
    shown = tracing.describe_content("secret question", field="query")
    assert shown["docs_rag.query_text"] == "secret question"


def test_to_otel_span_lifts_gen_ai_attributes() -> None:
    row = {
        "ts": "2026-09-20T10:00:00+08:00",
        "kind": "answer",
        "trace_id": "abc123",
        "latency_ms": 1500.0,
        "gen_ai.system": "deepseek",
        "gen_ai.request.model": "deepseek-flash",
        "gen_ai.usage.input_tokens": 900,
        "gen_ai.usage.output_tokens": 120,
        "docs_rag.caller": "qa",
        "docs_rag.question_sha256": "deadbeef",
    }
    span = tracing.to_otel_span(row)
    assert span["name"] == "answer deepseek-flash"
    assert span["trace_id"] == "abc123"
    assert span["attributes"]["gen_ai.operation.name"] == "answer"
    assert span["attributes"]["gen_ai.usage.input_tokens"] == 900
    assert span["attributes"]["docs_rag.caller"] == "qa"
    assert "ts" not in span["attributes"]  # bookkeeping fields stay out of the span
    start = datetime.datetime.fromisoformat(span["start_time"])
    end = datetime.datetime.fromisoformat(span["end_time"])
    assert (end - start).total_seconds() == pytest.approx(1.5)


def test_export_writes_one_span_per_record(tmp_path: pathlib.Path) -> None:
    source = tmp_path / "traces-demo.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"ts": "2026-09-20T10:00:00+08:00", "kind": "retrieval", "trace_id": "1"},
                {"ts": "2026-09-20T10:00:01+08:00", "kind": "answer", "trace_id": "2", "gen_ai.request.model": "m"},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "spans.jsonl"
    assert tracing.export_otel_spans(source, out) == 2
    spans = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [span["name"] for span in spans] == ["retrieval", "answer m"]


def test_prune_removes_only_files_outside_the_retention_window(tmp_path: pathlib.Path) -> None:
    now = datetime.datetime(2026, 9, 20, 12, 0, 0, tzinfo=datetime.UTC)
    old = tmp_path / "traces-old.jsonl"
    fresh = tmp_path / "traces-fresh.jsonl"
    other = tmp_path / "queries-demo.log"
    for path in (old, fresh, other):
        path.write_text("x\n", encoding="utf-8")
    old_stamp = (now - datetime.timedelta(days=30)).timestamp()
    for path in (old, other):
        path.touch()
        os.utime(path, (old_stamp, old_stamp))

    removed = tracing.prune(14, directory=tmp_path, now=now)
    assert removed == ["traces-old.jsonl"]
    assert fresh.exists() and other.exists() and not old.exists()


def test_summarize_counts_kinds_latency_errors_and_tokens(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PRICE_INPUT_PER_MTOK", "1.0")
    monkeypatch.setenv("RAG_PRICE_OUTPUT_PER_MTOK", "4.0")
    path = tmp_path / "traces-demo.jsonl"
    rows = [
        {"kind": "retrieval", "latency_ms": 10.0, "docs_rag.error": False},
        {"kind": "retrieval", "latency_ms": 30.0, "docs_rag.error": True},
        {"kind": "answer", "latency_ms": 2000.0, "gen_ai.usage.input_tokens": 1000, "gen_ai.usage.output_tokens": 250},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    summary = tracing.summarize(path)
    assert summary["records"] == 3
    assert summary["by_kind"] == {"retrieval": 2, "answer": 1}
    assert summary["errors"] == 1
    assert summary["error_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert summary["latency_ms"]["retrieval"]["max"] == 30.0
    assert summary["gen_ai.usage.input_tokens"] == 1000
    assert summary["gen_ai.usage.output_tokens"] == 250
    assert summary["estimated_cost_usd"] == pytest.approx(1000 / 1e6 + 250 * 4 / 1e6)


def test_violations_flag_threshold_breaches_only() -> None:
    healthy = [
        {"kind": "retrieval", "latency_ms": 20.0, "docs_rag.error": False},
        {"kind": "answer", "latency_ms": 100.0, "docs_rag.error": False, "gen_ai.usage.input_tokens": 10},
    ]
    assert tracing.violations(healthy) == []

    breached = [
        {"kind": "answer", "latency_ms": 9000.0, "docs_rag.error": True, "gen_ai.usage.input_tokens": 10},
        {"kind": "answer", "latency_ms": 9000.0, "docs_rag.error": True},
    ]
    found = tracing.violations(breached, max_error_rate=0.2, max_p95_ms=5000, max_total_tokens=5)
    assert len(found) == 3
    assert any("error rate" in item for item in found)
    assert any("p95" in item for item in found)
    assert any("token total" in item for item in found)
