"""Test bootstrap.

ragconfig validates its corpus config at import time (RAG_CORPUS must name a corpus in
RAG_DIR/corpora.json), so the environment has to be in place before any test module
imports it. This conftest points RAG_DIR at a throwaway config and selects a corpus
named after the tests, keeping the suite independent of any deployment.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="docs_rag_tests_"))
(_TMP / "corpora.json").write_text(
    json.dumps(
        {
            "test": {
                "corpus_dir": "corpus/test",
                "data_dir": "data-test",
                "top_files": [],
                "doc_root_files": [],
                "roots": [],
                "exclude_dirs": [],
            }
        }
    ),
    encoding="utf-8",
)

os.environ.setdefault("RAG_CORPUS", "test")
os.environ.setdefault("RAG_DIR", str(_TMP))
