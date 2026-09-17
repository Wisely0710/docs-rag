#!/bin/bash
# Fetch a public markdown corpus and assemble a self-contained RAG_DIR for eval runs.
#
# Usage: ./eval/fetch_corpus.sh [--ref <git-ref>] [--out <dir>] [--repo <url>]
#
# Defaults: repo=rust-lang/book ref=main out=eval/.work  (see eval/README.md)
# Written under <out>:
#   corpora.json                     one corpus: "book"
#   corpus/book/docs/book/*.md       the source tree's *.md, mirrored
#   corpus/book/.corpus_source.json  freshness marker (source_commit/synced_at/dirty)
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="https://github.com/rust-lang/book.git"
REF="main"
OUT="eval/.work"

while [ $# -gt 0 ]; do
    case "$1" in
    --repo) REPO="${2:?}"; shift 2 ;;
    --ref) REF="${2:?}"; shift 2 ;;
    --out) OUT="${2:?}"; shift 2 ;;
    -h | --help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

CHECKOUT="$OUT/source"
CORPUS="$OUT/corpus/book"

rm -rf "$CHECKOUT"
mkdir -p "$CHECKOUT" "$CORPUS/docs/book" "$OUT"

echo "fetching $REPO @ $REF"
git clone -q --depth 1 --branch "$REF" "$REPO" "$CHECKOUT"
COMMIT="$(git -C "$CHECKOUT" rev-parse HEAD)"

# Mirror *.md only (the service indexes markdown; listings/ and img/ are out of scope).
while IFS= read -r -d '' file; do
    rel="${file#"$CHECKOUT"/src/}"
    mkdir -p "$CORPUS/docs/book/$(dirname "$rel")"
    cp "$file" "$CORPUS/docs/book/$rel"
done < <(find "$CHECKOUT/src" -name '*.md' -print0 | sort -z)

cat >"$OUT/corpora.json" <<'JSON'
{
  "book": {
    "corpus_dir": "corpus/book",
    "data_dir": "data-book",
    "top_files": [],
    "doc_root_files": [],
    "roots": ["docs/book"],
    "exclude_dirs": [],
    "server_name": "book-docs-rag",
    "system_note": "cite the returned file path"
  }
}
JSON

printf '{"source_commit": "%s", "synced_at": "%s", "dirty": false}\n' \
    "$COMMIT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$CORPUS/.corpus_source.json"

echo "corpus: $CORPUS"
echo "commit: $COMMIT"
echo "files:  $(find "$CORPUS/docs/book" -name '*.md' | wc -l | tr -d ' ')"
