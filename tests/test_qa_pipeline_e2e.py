"""End-to-end: the ask CLI answers from a real index, offline (stub chat + stub embeddings).

Runs the real indexer as a subprocess against a throwaway RAG_DIR, then the real CLI, so
the retrieval wiring, the corpus selection and the citation extraction are all exercised;
only the chat model is substituted (the deterministic stub).
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

VERIFIER_DOC = (
    "# Verifier\n\n"
    "The verifier never custodies keys. It checks the signed payment and returns the verified\n"
    "facts; settlement happens later and is owned by the resource server.\n"
)


def _build_workspace(tmp_path: pathlib.Path) -> None:
    (tmp_path / "corpora.json").write_text(
        json.dumps(
            {
                "demo": {
                    "corpus_dir": "corpus/demo",
                    "data_dir": "data-demo",
                    "top_files": [],
                    "doc_root_files": [],
                    "roots": ["docs/notes"],
                    "exclude_dirs": [],
                }
            }
        ),
        encoding="utf-8",
    )
    notes = tmp_path / "corpus" / "demo" / "docs" / "notes"
    notes.mkdir(parents=True)
    (notes / "verifier.md").write_text(VERIFIER_DOC, encoding="utf-8")


def _run(args: list[str], tmp_path: pathlib.Path) -> subprocess.CompletedProcess[str]:
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
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_ask_cli_answers_with_a_citation_and_abstains_off_topic(tmp_path: pathlib.Path) -> None:
    _build_workspace(tmp_path)

    indexed = _run(["indexer.py"], tmp_path)
    assert indexed.returncode == 0, indexed.stderr

    answered = _run(
        [
            "qa/ask.py",
            "--rag-dir",
            str(tmp_path),
            "--corpus",
            "demo",
            "--backend",
            "stub",
            "--embed-backend",
            "stub",
            "--json",
            "Does the verifier custody keys?",
        ],
        tmp_path,
    )
    assert answered.returncode == 0, answered.stderr
    payload = json.loads(answered.stdout)
    assert payload["abstained"] is False
    assert payload["citations"] == ["docs/notes/verifier.md"]
    assert payload["sources"][0]["path"] == "docs/notes/verifier.md"

    refused = _run(
        [
            "qa/ask.py",
            "--rag-dir",
            str(tmp_path),
            "--corpus",
            "demo",
            "--backend",
            "stub",
            "--embed-backend",
            "stub",
            "--json",
            "What is the capital of France?",
        ],
        tmp_path,
    )
    assert refused.returncode == 0, refused.stderr
    payload = json.loads(refused.stdout)
    assert payload["abstained"] is True
    assert payload["citations"] == []
