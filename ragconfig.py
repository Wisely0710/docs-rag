"""Shared config + LM Studio embedding client for the per-project docs RAG services.

Runs on the docs-RAG host (LM Studio + embeddings on the same machine).
Version-controlled; corpus scope/layout comes from corpora.json (see load_corpora()).
One service instance per corpus; select with RAG_CORPUS (mandatory — the service
refuses to guess rather than silently serving the wrong corpus).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import pathlib
import re
import time
import urllib.error
import urllib.request

RAG_DIR = pathlib.Path(os.environ.get("RAG_DIR", str(pathlib.Path.home() / "rag-service")))
LOGS_DIR = RAG_DIR / "logs"
ENV_PATH = RAG_DIR / ".env"

RAG_CORPUS = os.environ.get("RAG_CORPUS", "").strip()
if not RAG_CORPUS:
    raise RuntimeError(
        "RAG_CORPUS is not set; this service is multi-tenant and refuses to guess. "
        f"Set RAG_CORPUS to one of the corpora in {RAG_DIR / 'corpora.json'}"
    )

# Corpus layout/scope/presentation is DATA, not code: every corpus is declared in
# corpora.json (schema: corpora.example.json). Nothing tenant-specific lives in this
# module, so adding a corpus — or retargeting one — never requires editing shared code,
# and one tenant's change cannot affect another.
_REQUIRED_KEYS = ("corpus_dir", "data_dir", "top_files", "doc_root_files", "roots", "exclude_dirs")


def load_corpora() -> dict[str, dict]:
    """Corpora declared in RAG_DIR/corpora.json; keys starting with "_" are metadata."""
    path = RAG_DIR / "corpora.json"
    if not path.exists():
        raise RuntimeError(f"no corpus config at {path}; copy corpora.example.json there and edit it")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"corpora.json unreadable/invalid ({path}): {exc!r}") from exc
    if not isinstance(data, dict):
        raise TypeError(f"corpora.json must be a JSON object ({path})")
    corpora: dict[str, dict] = {}
    for name, spec in data.items():
        if name.startswith("_"):
            continue
        if not isinstance(spec, dict):
            raise TypeError(f"corpora.json[{name!r}] must be a JSON object ({path})")
        missing = [key for key in _REQUIRED_KEYS if key not in spec]
        if missing:
            raise RuntimeError(f"corpora.json[{name!r}] is missing required keys {missing} ({path})")
        corpora[name] = spec
    return corpora


CORPORA = load_corpora()
if RAG_CORPUS not in CORPORA:
    raise RuntimeError(
        f"unknown corpus {RAG_CORPUS!r}; known: {sorted(CORPORA)} (define it in {RAG_DIR / 'corpora.json'})"
    )

_spec = CORPORA[RAG_CORPUS]
CORPUS_DIR = pathlib.Path(os.environ.get("RAG_CORPUS_DIR", str(RAG_DIR / str(_spec["corpus_dir"]))))
DATA_DIR = RAG_DIR / str(_spec["data_dir"])
CORPUS_TOP_FILES = [str(item) for item in _spec["top_files"]]
CORPUS_DOC_ROOT_FILES = [str(item) for item in _spec["doc_root_files"]]
CORPUS_ROOTS = [str(item) for item in _spec["roots"]]
CORPUS_EXCLUDE_DIRS = tuple(str(item) for item in _spec["exclude_dirs"])
# Optional per-corpus keys: presentation for the MCP server, and the local checkout whose
# git origin refresh.sh clones from when the corpus is git-backed.
CORPUS_GIT_ORIGIN_REPO = str(_spec.get("git_origin_repo") or "")
SERVER_NAME = os.environ.get("RAG_SERVER_NAME") or str(_spec.get("server_name") or f"{RAG_CORPUS}-docs-rag")
SYSTEM_NOTE = os.environ.get("RAG_SYSTEM_NOTE") or str(_spec.get("system_note") or "回答引用時請標明回傳的檔案路徑。")

DB_PATH = DATA_DIR / "index.sqlite"

# Chunking budget (chars). Measured tok_per_char = 1.9 on this zh+en corpus
# (nomic tokenizer) => 150..420 chars ~= 285..800 tokens, the planned 300-800 tok
# band; long paragraphs slide with ~80 char overlap (~150 tok worst case).
CHUNK_MIN_CHARS = 150
CHUNK_MAX_CHARS = 420
CHUNK_OVERLAP_CHARS = 80

EMBED_DIM = 768


def _load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env()

LMSTUDIO_BASE = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
LMSTUDIO_API_KEY = os.environ.get("LMSTUDIO_API_KEY", "")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")
# "stub" swaps the embedding model for a deterministic lexical pseudo-embedding
# (no network, no model server) so tests and the bundled demo run anywhere.
EMBED_BACKEND = os.environ.get("RAG_EMBED_BACKEND", "lmstudio")
HOST = os.environ.get("RAG_HOST", "0.0.0.0")
PORT = int(os.environ.get("RAG_PORT", "8765"))


_STUB_TOKEN_RE = re.compile(r"[0-9A-Za-z_]+|[\u4e00-\u9fff]")


def _stub_tokens(text: str) -> list[str]:
    """ASCII words + CJK characters + CJK bigrams (cheap lexical features for zh text)."""
    tokens = _STUB_TOKEN_RE.findall(text.lower())
    cjk = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    tokens.extend(cjk[i : i + 2] for i in range(len(cjk) - 1))
    return tokens


def stub_embed(texts: list[str]) -> tuple[list[list[float]], int]:
    """Deterministic hashed bag-of-tokens embedding — tests/demo only, no model server.

    Lexical overlap drives similarity, which is enough for the bundled demo and the
    end-to-end test: the FTS ranker also matches lexically and RRF fuses both lists.
    """
    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * EMBED_DIM
        for token in _stub_tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            vec[int.from_bytes(digest, "big") % EMBED_DIM] += 1.0
        norm = math.sqrt(sum(value * value for value in vec)) or 1.0
        vectors.append([value / norm for value in vec])
    return vectors, 0


def embed_texts(texts: list[str], batch: int = 32) -> tuple[list[list[float]], int]:
    """Embed in batches; returns (vectors, total_prompt_tokens). Retries on 429/5xx/network."""
    if EMBED_BACKEND == "stub":
        return stub_embed(texts)
    vectors: list[list[float]] = []
    total_tokens = 0
    for start in range(0, len(texts), batch):
        part = texts[start : start + batch]
        body = json.dumps({"model": EMBED_MODEL, "input": part}).encode("utf-8")
        req = urllib.request.Request(
            LMSTUDIO_BASE + "/embeddings",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        if LMSTUDIO_API_KEY:
            req.add_header("Authorization", "Bearer " + LMSTUDIO_API_KEY)
        last: Exception | None = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    payload = json.load(resp)
                items = sorted(payload.get("data", []), key=lambda d: d.get("index", 0))
                vectors.extend(d["embedding"] for d in items)
                total_tokens += int(payload.get("usage", {}).get("total_tokens", 0))
                break
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (429, 500, 502, 503, 504):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
            except OSError as exc:
                last = exc
                time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"embedding request failed after retries: {last!r}")
    return vectors, total_tokens
