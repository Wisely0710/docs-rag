#!/bin/bash
# Zero-dependency demo: index a synthetic corpus and retrieve from it.
#
# Needs no model server, no API key and no network: it uses RAG_EMBED_BACKEND=stub, a
# deterministic hashed bag-of-tokens embedding. Everything happens in a throwaway
# RAG_DIR, so this repo is left untouched.
#
# Usage: bash demo.sh        (override with PYTHON=/path/to/python3)
set -euo pipefail
cd "$(dirname "$0")"

if [ -n "${PYTHON:-}" ]; then
    PY="$PYTHON"
elif [ -x .venv/bin/python ]; then
    PY=".venv/bin/python"
else
    PY="python3"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export RAG_DIR="$WORK" RAG_CORPUS=demo RAG_EMBED_BACKEND=stub

echo "▸ 工作目錄（用完即刪）：$WORK"
echo "▸ 直譯器：$PY"

# 1) A corpus defined entirely by configuration + markdown — no code involved.
mkdir -p "$WORK/corpus/demo/docs/notes/archive"
cat >"$WORK/corpora.json" <<'JSON'
{
  "demo": {
    "corpus_dir": "corpus/demo",
    "data_dir": "data-demo",
    "top_files": ["AGENTS.md"],
    "doc_root_files": ["README.md"],
    "roots": ["docs/notes"],
    "exclude_dirs": ["archive"]
  }
}
JSON

cat >"$WORK/corpus/demo/AGENTS.md" <<'MD'
# Demo corpus

This file sits at the corpus root and is declared in `top_files`.
MD

cat >"$WORK/corpus/demo/docs/README.md" <<'MD'
# Docs root file

Declared in `doc_root_files` — resolved as `<corpus_dir>/docs/<name>`.
MD

cat >"$WORK/corpus/demo/docs/notes/retrieval.md" <<'MD'
# Retrieval design

Queries run two independent rankers and fuse them. The vector ranker embeds the query and
runs a KNN scan over chunk embeddings, which handles paraphrase but blurs rare tokens. The
FTS5 trigram ranker matches exact strings such as identifiers, file paths and error codes.

The fused score is sum(1 / (60 + rank)) over both ranker lists — reciprocal rank fusion
with k=60. RRF needs no score calibration between rankers, which is why it is preferred
over weighted score blending here.
MD

cat >"$WORK/corpus/demo/docs/notes/archive/old.md" <<'MD'
# Excluded

This file lives under `docs/notes/archive/`, which `exclude_dirs` removes. A retrieval
that returns it means exclusion is broken.
MD

# 2) Index it (incremental; a second run is a no-op).
echo
echo "▸ 建立索引…"
"$PY" indexer.py

# 3) Retrieve.
echo
echo "▸ 檢索（k=2）："
printf 'reciprocal rank fusion why not weighted score blending\n' | "$PY" ragquery.py -k 2

echo
echo "▸ 索引狀態："
"$PY" - <<'PY'
import json
import searchlib

print(json.dumps(searchlib.corpus_stats(), ensure_ascii=False, indent=2))
PY

echo
echo "✅ demo 完成（語料與索引都在臨時目錄，已刪除）"
