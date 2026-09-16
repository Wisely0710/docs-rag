"""End-to-end: a corpus defined purely in corpora.json is indexed and retrieved.

Runs the real indexer and query CLI as subprocesses against a throwaway RAG_DIR, with
RAG_EMBED_BACKEND=stub so no model server or network is required.
"""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

TOP_DOC = (
    "# Demo corpus\n\n"
    "This file is a project-level document. It exists so the end-to-end test can assert that\n"
    "top-level files listed in the corpus config are picked up by the indexer and that a\n"
    "retrieval can reach them.\n"
)
RETRIEVAL_DOC = (
    "# Retrieval design\n\n"
    "Queries run two independent rankers and fuse them. The vector ranker embeds the query and\n"
    "runs a KNN scan over chunk embeddings; it handles paraphrase but blurs rare tokens. The\n"
    "FTS5 trigram ranker matches exact strings such as identifiers, file paths and error codes.\n\n"
    "The fused score is sum(1 / (60 + rank)) over both ranker lists, i.e. reciprocal rank fusion\n"
    "with k=60. RRF needs no score calibration between rankers, which is why it is preferred\n"
    "here over weighted score blending.\n"
)


def _build_workspace(tmp_path: pathlib.Path) -> None:
    (tmp_path / "corpora.json").write_text(
        json.dumps(
            {
                "demo": {
                    "corpus_dir": "corpus/demo",
                    "data_dir": "data-demo",
                    "top_files": ["AGENTS.md"],
                    "doc_root_files": ["README.md"],
                    "roots": ["docs/notes"],
                    "exclude_dirs": ["archive"],
                }
            }
        ),
        encoding="utf-8",
    )
    corpus = tmp_path / "corpus" / "demo"
    (corpus / "docs" / "notes" / "archive").mkdir(parents=True)
    (corpus / "AGENTS.md").write_text(TOP_DOC, encoding="utf-8")
    (corpus / "docs" / "README.md").write_text("# Docs root file\n\nPlaceholder.\n", encoding="utf-8")
    (corpus / "docs" / "notes" / "retrieval.md").write_text(RETRIEVAL_DOC, encoding="utf-8")
    (corpus / "docs" / "notes" / "archive" / "old.md").write_text("# Excluded\n\nNever indexed.\n", encoding="utf-8")


def _run(args: list[str], tmp_path: pathlib.Path, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "RAG_DIR": str(tmp_path),
        "RAG_CORPUS": "demo",
        "RAG_EMBED_BACKEND": "stub",
    }
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_new_corpus_is_indexed_and_retrievable(tmp_path: pathlib.Path) -> None:
    _build_workspace(tmp_path)

    indexed = _run(["indexer.py"], tmp_path)
    assert indexed.returncode == 0, indexed.stderr

    db = sqlite3.connect(tmp_path / "data-demo" / "index.sqlite")
    try:
        paths = sorted(row[0] for row in db.execute("SELECT path FROM files"))
    finally:
        db.close()
    assert paths == ["AGENTS.md", "docs/README.md", "docs/notes/retrieval.md"]

    answer = _run(["ragquery.py", "-k", "2"], tmp_path, stdin="reciprocal rank fusion RRF k=60\n")
    assert answer.returncode == 0, answer.stderr
    assert "docs/notes/retrieval.md" in answer.stdout
    assert "archive" not in answer.stdout

    # the same query returns the top-level doc when asked about its own content
    top = _run(["ragquery.py", "-k", "1"], tmp_path, stdin="top-level files listed in the corpus config\n")
    assert top.returncode == 0, top.stderr
    assert "AGENTS.md" in top.stdout
