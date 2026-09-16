#!/bin/bash
# Push a documentation tree into a docs-rag corpus mirror and re-index it.
#
# Usage: ./client/sync_corpus.sh --corpus <name> --source <repo-root> [options]
#
#   --corpus <name>      corpus as declared in the service's corpora.json (required)
#   --source <dir>       local repository root holding the documents (required)
#   --host <ssh-host>    ssh host running the service            (default: $RAG_HOST)
#   --service-dir <dir>  remote docs-rag checkout                (default: /srv/docs-rag)
#   --remote-dir <dir>   remote corpus dir  (default: <service-dir>/corpus/<corpus>)
#   --dry-run            print the scope and the transfer, change nothing
#
# The corpus scope (which files/trees, what to exclude) is read from the service's
# own config at run time — this script keeps no second copy of it, so a scope change on
# the service side cannot silently drift from what is pushed.
#
# The target is guarded: --remote-dir must be exactly <service-dir>/corpus/<corpus>, so a
# typo cannot make one corpus overwrite another (the transfer uses --delete).
set -euo pipefail

CORPUS=""
SOURCE=""
HOST="${RAG_HOST:-}"
SERVICE_DIR=""
REMOTE_DIR=""
DRY_RUN=0

while [ $# -gt 0 ]; do
    case "$1" in
    --corpus) CORPUS="${2:?}"; shift 2 ;;
    --source) SOURCE="${2:?}"; shift 2 ;;
    --host) HOST="${2:?}"; shift 2 ;;
    --service-dir) SERVICE_DIR="${2:?}"; shift 2 ;;
    --remote-dir) REMOTE_DIR="${2:?}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h | --help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "❌ 未知參數：$1（--help 看用法）" >&2; exit 2 ;;
    esac
done

[ -n "$CORPUS" ] || { echo "❌ --corpus 必填" >&2; exit 2; }
[ -n "$SOURCE" ] || { echo "❌ --source 必填" >&2; exit 2; }
[ -n "$HOST" ] || { echo "❌ --host 必填（或設 RAG_HOST）" >&2; exit 2; }
[ -n "$SERVICE_DIR" ] || { echo "❌ --service-dir 必填" >&2; exit 2; }
[ -d "$SOURCE" ] || { echo "❌ --source 不是目錄：$SOURCE" >&2; exit 2; }

REMOTE_DIR="${REMOTE_DIR:-${SERVICE_DIR}/corpus/${CORPUS}}"

# Guard ①: the corpus name must be a plain token (no glob metacharacters).
case "$CORPUS" in
'' | *[!A-Za-z0-9_-]*)
    echo "❌ 拒絕執行：--corpus '$CORPUS' 含非安全字元（僅允許 A-Za-z0-9_-）" >&2
    exit 1
    ;;
esac
# Guard ②: the target must be THIS corpus's directory — comparing only .../corpus/ would
# let one corpus overwrite another tenant's mirror (--delete removes everything else).
case "$REMOTE_DIR" in
"${SERVICE_DIR}/corpus/${CORPUS}") ;;
*)
    echo "❌ 拒絕執行：--remote-dir '$REMOTE_DIR' ≠ '${SERVICE_DIR}/corpus/${CORPUS}'（--delete 保護；請確認路徑本身、勿加尾斜線）" >&2
    exit 1
    ;;
esac

cd "$SOURCE"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

echo "🔄 [$(date)] corpus '${CORPUS}'：${SOURCE} → ${HOST}:${REMOTE_DIR}"

# 1) Derive the scope from the service's config (program via stdin: no nested quoting).
scope_out="$(ssh -o BatchMode=yes "$HOST" "cd '${SERVICE_DIR}' && RAG_CORPUS='${CORPUS}' .venv/bin/python -" <<'PY'
import ragconfig as rc

for name in rc.CORPUS_TOP_FILES:
    print("I", name)
for name in rc.CORPUS_DOC_ROOT_FILES:
    print("I", "docs/" + name)
for name in rc.CORPUS_ROOTS:
    print("I", name)
for name in rc.CORPUS_EXCLUDE_DIRS:
    print("X", name)
PY
)"

includes=()
excludes=()
while read -r kind path; do
    [ -n "${path:-}" ] || continue
    case "$kind" in
    I) includes+=("$path") ;;
    X) excludes+=("$path") ;;
    esac
done <<<"$scope_out"

if [ "${#includes[@]}" -eq 0 ]; then
    echo "❌ 語料範圍推導為空（服務端設定不可達或 CORPUS_* 為空）——中止，未推送" >&2
    exit 1
fi
echo "  範圍（單源＝服務端設定）：${#includes[@]} 項入口、${#excludes[@]} 項排除"

# 2) Assemble the payload locally (-R keeps the relative layout).
if [ "${#excludes[@]}" -gt 0 ]; then
    rsync_excludes=()
    for ex in "${excludes[@]}"; do rsync_excludes+=("--exclude=${ex}/"); done
    rsync -aR "${rsync_excludes[@]}" "${includes[@]}" "$STAGING/"
else
    rsync -aR "${includes[@]}" "$STAGING/"
fi

# 3) Freshness marker (only meaningful for git-backed sources; a non-git --source still
#    syncs — the marker then records source_commit=unknown, dirty=false).
if node="$(git rev-parse --short HEAD 2>/dev/null)"; then
    dirty_count="$(git status --porcelain -- "${includes[@]}" 2>/dev/null | wc -l | tr -d ' ')"
else
    node="unknown"
    dirty_count=0
fi
if [ "$dirty_count" -gt 0 ]; then dirty_flag=true; else dirty_flag=false; fi
printf '{"source_commit": "%s", "synced_at": "%s", "dirty": %s}\n' \
    "$node" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$dirty_flag" >"$STAGING/.corpus_source.json"

if [ "$DRY_RUN" -eq 1 ]; then
    echo "▸ dry-run：以下為將推送的內容（未傳輸、未變更；範圍推導已連線服務端）"
    (cd "$STAGING" && find . -type f | sort | sed 's/^/    /')
    exit 0
fi

# 4) Transfer (--delete drops documents that left the scope). Remote one-liners go via
#    `sh -s -- <args>`: values arrive as positional parameters (no client-side expansion
#    inside the remote command string; paths with spaces or quotes stay intact).
ssh "$HOST" sh -s -- "$REMOTE_DIR" <<'EOF'
mkdir -p -- "$1"
EOF
rsync -a --delete "$STAGING/" "${HOST}:${REMOTE_DIR}/"

# 5) Incremental re-index. The service takes a lock and a busy indexer is reported, not
#    queued — retry briefly and, if it is still busy, fail loudly: the corpus is synced,
#    the index is behind and the next indexer run catches up.
echo "🧠 增量重索引："
attempt=1
while :; do
    out="$(
        ssh "$HOST" sh -s -- "$SERVICE_DIR" "$CORPUS" 2>&1 <<'EOF'
cd "$1" || exit 1
RAG_CORPUS="$2" .venv/bin/python indexer.py
EOF
    )"
    printf '%s\n' "$out" | tail -4
    # The indexer prints a line starting with "skip:" when another run holds .index.lock.
    case "$out" in
    *"skip:"*)
        if [ "$attempt" -ge 3 ]; then
            echo "❌ 索引器連續忙碌（.index.lock）；語料已同步、索引延後（下次 indexer 執行補上）" >&2
            exit 1
        fi
        echo "⏳ 索引器忙碌，30 秒後重試（第 ${attempt} 次）"
        attempt=$((attempt + 1))
        sleep 30
        continue
        ;;
    esac
    break
done

echo "✅ [$(date)] corpus '${CORPUS}' 同步完成（source_commit=${node}, dirty=${dirty_count} 檔未提交）"
