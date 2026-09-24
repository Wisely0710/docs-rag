"""Run traces for the service and the QA layer — one JSON object per line.

Why JSONL and not the OpenTelemetry SDK: this service must import, run and be tested
with no network and no extra dependency (CI runs offline, and the deployment is a single
host with a SQLite index). The records carry the OpenTelemetry **GenAI semantic
convention attribute names** for everything the conventions cover
(``gen_ai.operation.name`` / ``gen_ai.system`` / ``gen_ai.request.model`` /
``gen_ai.usage.input_tokens`` / ``gen_ai.usage.output_tokens``), so
:func:`to_otel_span` and :func:`export_otel_spans` lift a record into a span-shaped
document without a translation table. Service-specific facts live under ``docs_rag.``.

Two policies are deliberate:

- **Content is hashed by default.** A retrieval/answer trace stores SHA-256 digests and
  lengths of the prompt and the completion; set ``RAG_TRACE_CONTENT=1`` to store the raw
  text. Traces are diagnostic evidence, not the thing they were meant to protect.
- **Retention is a window.** :func:`prune` deletes whole trace files older than
  ``RAG_TRACE_KEEP_DAYS`` (default 14). Nothing prunes automatically — the deployment
  schedules it (see README "Observability").
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import statistics
from collections.abc import Mapping
from typing import Any

DEFAULT_KEEP_DAYS = 14
CONTENT_ENV = "RAG_TRACE_CONTENT"
KEEP_DAYS_ENV = "RAG_TRACE_KEEP_DAYS"
TRACE_FILE_PREFIX = "traces-"
TRACE_FILE_SUFFIX = ".jsonl"

#: Attribute keys copied verbatim into an OTel span's ``attributes``.
_OTEL_PREFIXES = ("gen_ai.", "docs_rag.")


def trace_dir(directory: pathlib.Path | str | None = None) -> pathlib.Path:
    """Directory holding the trace files: ``RAG_TRACE_DIR``, else the service log dir.

    ``ragconfig`` is imported lazily so that reading, exporting or pruning traces — the
    ``tracing.py`` CLI — never requires a corpus configuration (an operator diagnosing a
    failed deployment must not need the corpus that deployment was serving).
    """
    if directory is not None:
        return pathlib.Path(directory)
    override = os.environ.get("RAG_TRACE_DIR", "").strip()
    if override:
        return pathlib.Path(override)
    from ragconfig import LOGS_DIR

    return pathlib.Path(LOGS_DIR)


def trace_path(corpus: str | None = None, directory: pathlib.Path | str | None = None) -> pathlib.Path:
    """Per-corpus trace file, so one corpus never shares a file with another."""
    name = corpus or os.environ.get("RAG_CORPUS", "default")
    return trace_dir(directory) / f"{TRACE_FILE_PREFIX}{name}{TRACE_FILE_SUFFIX}"


def content_enabled() -> bool:
    """True when raw prompt/completion text may be stored (opt-in)."""
    return os.environ.get(CONTENT_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def describe_content(text: str | None, *, field: str) -> dict[str, Any]:
    """Hashed description of a text field; the raw text only under the opt-in policy."""
    if text is None:
        return {}
    payload: dict[str, Any] = {
        f"docs_rag.{field}_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        f"docs_rag.{field}_chars": len(text),
    }
    if content_enabled():
        payload[f"docs_rag.{field}_text"] = text
    return payload


def record(
    kind: str,
    fields: Mapping[str, Any] | None = None,
    *,
    corpus: str | None = None,
    directory: pathlib.Path | str | None = None,
    trace_id: str | None = None,
    latency_ms: float | None = None,
) -> dict[str, Any]:
    """Append one trace record and return it.

    ``fields`` carries the per-event payload as a mapping (rather than ``**kwargs``) so
    both the call sites and the type checker see the same shape: OTel attribute names for
    everything the conventions cover, ``docs_rag.*`` for service facts.

    Best effort by design: a trace write failure (permissions, disk) never fails the
    call being traced — the same rule the metering line already follows.
    """
    row: dict[str, Any] = {
        "ts": datetime.datetime.now(datetime.UTC).astimezone().isoformat(timespec="milliseconds"),
        "kind": kind,
        "docs_rag.corpus": corpus or os.environ.get("RAG_CORPUS", "default"),
        "trace_id": trace_id or os.urandom(8).hex(),
    }
    if latency_ms is not None:
        row["latency_ms"] = round(float(latency_ms), 1)
    row.update(fields or {})
    try:
        path = trace_path(corpus, directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return row


def read_records(path: pathlib.Path | str) -> list[dict[str, Any]]:
    """Every parseable record in a trace file (blank/corrupt lines are skipped)."""
    rows: list[dict[str, Any]] = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def to_otel_span(row: dict[str, Any]) -> dict[str, Any]:
    """Map one trace record onto a span-shaped document (pure function)."""
    start = _parse_ts(row.get("ts"))
    latency_ms = float(row.get("latency_ms") or 0.0)
    end = start + datetime.timedelta(milliseconds=latency_ms) if start else None
    attributes = {key: value for key, value in row.items() if key.startswith(_OTEL_PREFIXES)}
    attributes.setdefault("gen_ai.operation.name", str(row.get("kind", "unknown")))
    name = str(row.get("kind", "record"))
    model = row.get("gen_ai.request.model")
    if isinstance(model, str) and model:
        name = f"{name} {model}"
    return {
        "name": name,
        "trace_id": row.get("trace_id"),
        "start_time": start.isoformat() if start else str(row.get("ts")),
        "end_time": end.isoformat() if end else None,
        "attributes": attributes,
    }


def export_otel_spans(source: pathlib.Path | str, destination: pathlib.Path | str) -> int:
    """Write the records of ``source`` as span-shaped JSON lines; returns the count.

    This is the dependency-free export path: the result is what an OTel exporter (or a
    collector's file receiver) consumes, without importing the SDK here.
    """
    rows = read_records(source)
    out = pathlib.Path(destination)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(to_otel_span(row), ensure_ascii=False) + "\n" for row in rows)
    return len(rows)


def prune(
    days: int | None = None,
    *,
    directory: pathlib.Path | str | None = None,
    now: datetime.datetime | None = None,
) -> list[str]:
    """Delete whole trace files older than the retention window; returns their names."""
    window = days if days is not None else int(os.environ.get(KEEP_DAYS_ENV, DEFAULT_KEEP_DAYS))
    current = now or datetime.datetime.now(datetime.UTC)
    cutoff = current.timestamp() - window * 86400
    removed: list[str] = []
    for path in sorted(trace_dir(directory).glob(f"{TRACE_FILE_PREFIX}*{TRACE_FILE_SUFFIX}")):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed.append(path.name)
        except OSError:
            continue
    return removed


def summarize(path: pathlib.Path | str) -> dict[str, Any]:
    """Usage/latency summary of a trace file: the meter behind ``tracing.py --report``."""
    return summarize_rows(read_records(path))


def estimate_cost(input_tokens: int, output_tokens: int) -> float | None:
    """Cost estimate from the deployment's price table; ``None`` when no prices are set."""
    price_in = _env_float("RAG_PRICE_INPUT_PER_MTOK")
    price_out = _env_float("RAG_PRICE_OUTPUT_PER_MTOK")
    if price_in is None and price_out is None:
        return None
    cost = input_tokens * (price_in or 0.0) / 1e6 + output_tokens * (price_out or 0.0) / 1e6
    return round(cost, 6)


def violations(
    rows: list[dict[str, Any]],
    *,
    max_error_rate: float = 0.2,
    max_p95_ms: float = 5000.0,
    max_total_tokens: int | None = None,
) -> list[str]:
    """Threshold checks a scheduler (or a human) can run over a trace window.

    Deliberately returns plain sentences: the point is that an alert rule and its owner
    exist in the repo, not that this function pages anyone (see README, Observability).
    """
    if not rows:
        return []
    summary = summarize_rows(rows)
    found: list[str] = []
    if summary["error_rate"] > max_error_rate:
        found.append(
            f"error rate {summary['error_rate']:.1%} exceeds {max_error_rate:.0%} ({summary['errors']}/{summary['records']})"
        )
    for kind, stats in summary["latency_ms"].items():
        if stats["p95"] > max_p95_ms:
            found.append(f"{kind} p95 latency {stats['p95']:.0f}ms exceeds {max_p95_ms:.0f}ms")
    total_tokens = summary["gen_ai.usage.input_tokens"] + summary["gen_ai.usage.output_tokens"]
    if max_total_tokens is not None and total_tokens > max_total_tokens:
        found.append(f"token total {total_tokens} exceeds {max_total_tokens}")
    ceiling = _env_float("RAG_COST_ALERT_USD")
    cost = summary["estimated_cost_usd"]
    if ceiling is not None and cost is not None and cost > ceiling:
        found.append(f"estimated cost {cost:.4f} USD exceeds the configured ceiling {ceiling:.4f} USD")
    return found


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Same shape as :func:`summarize`, for callers that already hold the records."""
    by_kind: dict[str, int] = {}
    latencies: dict[str, list[float]] = {}
    errors = 0
    input_tokens = 0
    output_tokens = 0
    for row in rows:
        kind = str(row.get("kind", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if isinstance(row.get("latency_ms"), (int, float)):
            latencies.setdefault(kind, []).append(float(row["latency_ms"]))
        if row.get("docs_rag.error"):
            errors += 1
        input_tokens += int(row.get("gen_ai.usage.input_tokens") or 0)
        output_tokens += int(row.get("gen_ai.usage.output_tokens") or 0)
    return {
        "records": len(rows),
        "by_kind": by_kind,
        "errors": errors,
        "error_rate": round(errors / len(rows), 4) if rows else 0.0,
        "latency_ms": {kind: _percentiles(values) for kind, values in sorted(latencies.items())},
        "gen_ai.usage.input_tokens": input_tokens,
        "gen_ai.usage.output_tokens": output_tokens,
        "estimated_cost_usd": estimate_cost(input_tokens, output_tokens),
    }


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))
    return {
        "p50": round(statistics.median(ordered), 1),
        "p95": round(ordered[index], 1),
        "max": round(ordered[-1], 1),
    }


def _parse_ts(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def _env_float(name: str, default: float | None = None) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="trace report / export / retention (offline, no dependencies)")
    parser.add_argument("--report", metavar="TRACE_FILE", help="print a usage/latency summary")
    parser.add_argument("--export-otel", nargs=2, metavar=("TRACE_FILE", "OUT_FILE"), help="write span-shaped JSONL")
    parser.add_argument("--prune-days", type=int, metavar="N", help="delete trace files older than N days")
    parser.add_argument(
        "--check",
        nargs="+",
        metavar="TRACE_FILE",
        help="print threshold violations over one window (all files, in order; exit 1 when any)",
    )
    parser.add_argument("--max-error-rate", type=float, metavar="RATE", help="error-rate ceiling for --check")
    parser.add_argument("--max-p95-ms", type=float, metavar="MS", help="p95 latency ceiling for --check")
    parser.add_argument("--max-total-tokens", type=int, metavar="N", help="token-total ceiling for --check")
    args = parser.parse_args()

    if args.report:
        print(json.dumps(summarize(args.report), ensure_ascii=False, indent=2))
    if args.export_otel:
        print(f"exported {export_otel_spans(args.export_otel[0], args.export_otel[1])} spans")
    if args.prune_days is not None:
        print(f"pruned: {prune(args.prune_days)}")
    if args.check:
        # One window: the files are concatenated in the order given, so a rolling window
        # may be checked across several files without a separate merge step.
        rows = [row for path in args.check for row in read_records(path)]
        limits: dict[str, Any] = {}
        if args.max_error_rate is not None:
            limits["max_error_rate"] = args.max_error_rate
        if args.max_p95_ms is not None:
            limits["max_p95_ms"] = args.max_p95_ms
        if args.max_total_tokens is not None:
            limits["max_total_tokens"] = args.max_total_tokens
        found = violations(rows, **limits)
        for item in found:
            print(f"VIOLATION: {item}")
        return 1 if found else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
