#!/bin/bash
# Re-index one corpus, re-fetching first when the corpus is git-backed.
#
# Usage: ./refresh.sh <corpus> [git-ref]     (cron: one line per corpus)
#
# Everything tenant-specific comes from corpora.json (corpus_dir / data_dir /
# git_origin_repo) — this script contains no corpus names or absolute paths.
# For an rsync-mirrored corpus the content is pushed by the owning repo, so there is
# nothing to fetch here; for a git-backed corpus the local clone is refreshed from the
# origin of the checkout named by git_origin_repo.
set -euo pipefail
cd "$(dirname "$0")"
export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin

CORPUS="${1:?usage: refresh.sh <corpus> [git-ref]}"
REF="${2:-master}"
export RAG_CORPUS="$CORPUS"

PY=".venv/bin/python"
mkdir -p logs

CORPUS_DIR="$("$PY" -c 'import ragconfig as rc; print(rc.CORPUS_DIR)')"
ORIGIN_REPO="$("$PY" -c 'import ragconfig as rc; print(rc.CORPUS_GIT_ORIGIN_REPO)')"

if [ -n "$ORIGIN_REPO" ]; then
    if [ -d "$CORPUS_DIR/.git" ]; then
        git -C "$CORPUS_DIR" fetch --depth 1 origin "$REF"
        git -C "$CORPUS_DIR" reset --hard "origin/$REF"
    else
        URL="$(git -C "$ORIGIN_REPO" config --get remote.origin.url)"
        git clone --depth 1 --branch "$REF" "$URL" "$CORPUS_DIR"
    fi
fi

"$PY" indexer.py >>"logs/${CORPUS}.index.log" 2>&1
