#!/bin/bash
# Fetch the public portfolio corpora and assemble a self-contained RAG_DIR for QA eval runs.
#
# Usage: ./eval/qa/fetch_corpus.sh [--out <dir>]
#
# Defaults: out=eval/qa/.work
#
# The corpus is exactly the public documentation of the portfolio: every *.md file of the
# four public repositories, mirrored under corpus/portfolio/docs/<repo>/ (no VCS, virtualenv,
# cache, eval-fixture or generated-report files). The resolved commit of every repository is
# recorded, so a report is tied to the source revisions it ran against.
#
# Written under <out>:
#   corpora.json                             one corpus: "portfolio"
#   corpus/portfolio/docs/<repo>/*.md        the source trees' *.md, mirrored
#   corpus/portfolio/.corpus_source.json     freshness marker (per-repo commits, synced_at)
set -euo pipefail
cd "$(dirname "$0")/../.."

OUT="eval/qa/.work"
REPOS="x402-agent-payments grounding-guard llm-toolbox docs-rag"

while [ $# -gt 0 ]; do
    case "$1" in
    --out) OUT="${2:?}"; shift 2 ;;
    -h | --help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

CHECKOUT="$OUT/source"
CORPUS="$OUT/corpus/portfolio"
mkdir -p "$CHECKOUT" "$CORPUS/docs"

sources="{"
first=1
for repo in $REPOS; do
    echo "fetching Wisely0710/$repo"
    rm -rf "${CHECKOUT:?}/$repo"
    git clone -q --depth 1 "https://github.com/Wisely0710/$repo.git" "$CHECKOUT/$repo"
    commit="$(git -C "$CHECKOUT/$repo" rev-parse HEAD)"
    if [ "$first" -eq 1 ]; then first=0; else sources="$sources,"; fi
    sources="$sources\"$repo\":\"$commit\""

    while IFS= read -r -d '' file; do
        rel="${file#"$CHECKOUT/$repo"/}"
        case "$(basename "$file")" in LICENSE* | CHANGELOG* | report-*) continue ;; esac
        mkdir -p "$CORPUS/docs/$repo/$(dirname "$rel")"
        cp "$file" "$CORPUS/docs/$repo/$rel"
    done < <(find "$CHECKOUT/$repo" \
        \( -name .git -o -name .venv -o -name node_modules -o -name .pytest_cache \
        -o -name __pycache__ -o -name .mypy_cache -o -name .ruff_cache \) -prune -o \
        \( -path '*/eval/fixture' -o -path '*/eval/qa/fixture' \) -prune -o \
        -name '*.md' -print0 | sort -z)
done
sources="$sources}"

cat >"$OUT/corpora.json" <<'JSON'
{
  "portfolio": {
    "corpus_dir": "corpus/portfolio",
    "data_dir": "data-portfolio",
    "top_files": [],
    "doc_root_files": [],
    "roots": ["docs"],
    "exclude_dirs": [],
    "server_name": "portfolio-docs-rag",
    "system_note": "回答引用時請標明回傳的檔案路徑。"
  }
}
JSON

{
    printf '{"repos": %s, "synced_at": "%s", "dirty": false}\n' "$sources" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"$CORPUS/.corpus_source.json"

echo "corpus: $CORPUS"
echo "files:  $(find "$CORPUS/docs" -name '*.md' | wc -l | tr -d ' ')"
