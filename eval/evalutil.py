"""Shared helpers for the evaluation harnesses (retrieval: run_eval.py, answers: qa/run_qa_eval.py).

A harness must see exactly the same corpus configuration as the service: one process owns
exactly one corpus, and the RAG_* environment has to be in place before the service modules
are imported (their config is read at import time — the same contract as tests/conftest.py).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEXER = REPO_ROOT / "indexer.py"


def configure_env(*, rag_dir: Path, corpus: str, embed_backend: str | None = None) -> dict[str, str]:
    """Point the service modules at this run's corpus.

    Returns the environment to hand to subprocesses; passing embed_backend=None keeps the
    environment's RAG_EMBED_BACKEND (the default is the deployment's LM Studio server).
    """
    env = dict(os.environ)
    env["RAG_DIR"] = str(rag_dir.resolve())
    env["RAG_CORPUS"] = corpus
    env.pop("RAG_CORPUS_DIR", None)  # the corpus_dir declared in corpora.json must win
    if embed_backend:
        env["RAG_EMBED_BACKEND"] = embed_backend
    for key in ("RAG_DIR", "RAG_CORPUS", "RAG_EMBED_BACKEND"):
        if key in env:
            os.environ[key] = env[key]
    os.environ.pop("RAG_CORPUS_DIR", None)
    return env


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


def data_dir_for(rag_dir: Path, corpus: str) -> Path:
    """The corpus's data_dir, as declared in corpora.json (falls back to data-<corpus>)."""
    try:
        spec = json.loads((rag_dir / "corpora.json").read_text(encoding="utf-8"))[corpus]
        return rag_dir / str(spec["data_dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return rag_dir / f"data-{corpus}"


def load_jsonl(path: Path, *, required: tuple[str, ...]) -> list[dict[str, Any]]:
    """Load a JSONL label set: blank lines skipped, `//` and `#` comment lines ignored."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith(("//", "#")):
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise SystemExit(f"{path}:{lineno}: not valid JSON ({exc})") from exc
        for key in required:
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


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile (the two harnesses report the same latency statistic)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def display_location(rag_dir: Path) -> str:
    """A publishable description of where the corpus lives (no absolute user paths)."""
    try:
        return str(rag_dir.relative_to(REPO_ROOT))
    except ValueError:
        return f"<RAG_DIR>/{rag_dir.name}"


def shorten_hashes(text: str) -> str:
    """Trim 40-char hex digests to 8 chars: scanners read them as high-entropy strings."""
    return re.sub(r"\b[0-9a-f]{40}\b", lambda match: match.group(0)[:8], text)
