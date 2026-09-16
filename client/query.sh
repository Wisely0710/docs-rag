#!/bin/bash
# Query a docs-rag corpus from the shell (read-only; same code path as the MCP tool).
#
# Usage: ./client/query.sh --corpus <name> --query "<text>" [--k N] [options]
#
#   --corpus <name>      corpus as declared in the service's corpora.json (required)
#   --query "<text>"     query string (required; or pipe it on stdin)
#   --k <N>              results to return, 1-10                          (default: 4)
#   --host <ssh-host>    ssh host running the service            (default: $RAG_HOST)
#   --service-dir <dir>  remote docs-rag checkout                (default: /srv/docs-rag)
set -euo pipefail

CORPUS=""
QUERY=""
K=4
HOST="${RAG_HOST:-}"
SERVICE_DIR=""

while [ $# -gt 0 ]; do
    case "$1" in
    --corpus) CORPUS="${2:?}"; shift 2 ;;
    --query) QUERY="${2:?}"; shift 2 ;;
    --k) K="${2:?}"; shift 2 ;;
    --host) HOST="${2:?}"; shift 2 ;;
    --service-dir) SERVICE_DIR="${2:?}"; shift 2 ;;
    -h | --help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "❌ 未知參數：$1（--help 看用法）" >&2; exit 2 ;;
    esac
done

[ -n "$CORPUS" ] || { echo "❌ --corpus 必填" >&2; exit 2; }
[ -n "$HOST" ] || { echo "❌ --host 必填（或設 RAG_HOST）" >&2; exit 2; }
[ -n "$SERVICE_DIR" ] || { echo "❌ --service-dir 必填" >&2; exit 2; }

case "$K" in
'' | 0 | *[!0-9]*) echo "❌ --k 須為正整數（收到：'${K}'）" >&2; exit 2 ;;
esac

if [ -z "$QUERY" ]; then
    QUERY="$(cat)"
fi
[ -n "$QUERY" ] || { echo "❌ 查詢為空（--query 或 stdin）" >&2; exit 2; }

case "$CORPUS" in
'' | *[!A-Za-z0-9_-]*) echo "❌ --corpus '$CORPUS' 含非安全字元" >&2; exit 2 ;;
esac

printf '%s\n' "$QUERY" |
    ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" \
        "cd '${SERVICE_DIR}' && RAG_CORPUS='${CORPUS}' .venv/bin/python ragquery.py -k ${K}"
