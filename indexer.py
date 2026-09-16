"""Incremental indexer: corpus -> chunks -> nomic embeddings -> sqlite (FTS5 + vec0).

Usage: python3 indexer.py   (writes data/index.sqlite under RAG_DIR)
"""
from __future__ import annotations

import json
import math
import sqlite3
import struct
import subprocess
import sys
import time
from typing import Any

import ragconfig as cfg
from corpus import chunk_markdown, iter_corpus_files, relpath_of, sha256_file
from ragconfig import CHUNK_MAX_CHARS, CHUNK_MIN_CHARS, CHUNK_OVERLAP_CHARS, EMBED_DIM, embed_texts

DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files(
  path TEXT PRIMARY KEY,
  sha TEXT NOT NULL,
  mtime REAL NOT NULL,
  bytes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT NOT NULL,
  seq INTEGER NOT NULL,
  text TEXT NOT NULL,
  est_tokens INTEGER NOT NULL,
  vec BLOB
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  path UNINDEXED, text, tokenize='trigram'
);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path, seq);
"""

_TABLE_VEC = "CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(embedding float[768])"


def open_db() -> sqlite3.Connection:
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(cfg.DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(DDL)
    return db


def vec_enabled(db: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec

        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        db.execute(_TABLE_VEC)
        return True
    except (ImportError, OSError, sqlite3.Error):
        return False


def pack_vec(v: list[float]) -> bytes:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return struct.pack(f"<{EMBED_DIM}f", *(x / norm for x in v))


def _calibration(db: sqlite3.Connection) -> float:
    row = db.execute("SELECT value FROM meta WHERE key='tok_per_char'").fetchone()
    return float(row[0]) if row else 1.9


def _set_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def _delete_path(db: sqlite3.Connection, path: str, with_vec: bool) -> None:
    ids = [r[0] for r in db.execute("SELECT id FROM chunks WHERE path=?", (path,))]
    if ids:
        qmarks = ",".join("?" * len(ids))
        db.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({qmarks})", ids)
        if with_vec:
            db.execute(f"DELETE FROM vec_chunks WHERE rowid IN ({qmarks})", ids)
        db.execute(f"DELETE FROM chunks WHERE id IN ({qmarks})", ids)
    db.execute("DELETE FROM files WHERE path=?", (path,))


def index_one(db: sqlite3.Connection, path: str, text: str, seq_offset: int, cal: float, with_vec: bool) -> tuple[int, int, int]:
    """Insert chunks of one file. Returns (n_chunks, chars, tokens)."""
    chunks = chunk_markdown(text, CHUNK_MIN_CHARS, CHUNK_MAX_CHARS, CHUNK_OVERLAP_CHARS)
    if not chunks:
        return 0, 0, 0
    vectors, used_tokens = embed_texts(chunks)
    if len(vectors) != len(chunks):
        raise RuntimeError(f"embedding count mismatch for {path}: {len(vectors)} vs {len(chunks)}")
    dim_ok = all(len(v) == EMBED_DIM for v in vectors)
    if not dim_ok:
        raise RuntimeError(f"embedding dim mismatch for {path} (expected {EMBED_DIM})")
    total_chars = sum(len(c) for c in chunks)
    for seq, (chunk, vec) in enumerate(zip(chunks, vectors)):
        est = max(1, round(len(chunk) * cal)) if cal else len(chunk) // 2
        cur = db.execute(
            "INSERT INTO chunks(path, seq, text, est_tokens, vec) VALUES(?,?,?,?,?)",
            (path, seq + seq_offset, chunk, est, pack_vec(vec)),
        )
        cid = cur.lastrowid
        db.execute("INSERT INTO chunks_fts(rowid, path, text) VALUES(?,?,?)", (cid, path, chunk))
        if with_vec:
            db.execute("INSERT INTO vec_chunks(rowid, embedding) VALUES(?,?)", (cid, pack_vec(vec)))
    return len(chunks), total_chars, used_tokens


def run_index() -> dict:
    started = time.time()
    db = open_db()
    with_vec = vec_enabled(db)
    cal = _calibration(db)

    corpus_files = {relpath_of(p): p for p in iter_corpus_files()}
    known = {row[0]: (row[1], row[2]) for row in db.execute("SELECT path, sha, mtime FROM files")}
    changed = [rel for rel in corpus_files if rel not in known]
    stale = [rel for rel in known if rel not in corpus_files]
    for rel, p in corpus_files.items():
        if rel in known and known[rel][0] != sha256_file(p):
            changed.append(rel)

    summary: dict[str, Any] = {"vec": with_vec, "added": [], "removed": []}
    n_chunks = n_chars = n_tokens = 0
    db.execute("BEGIN")
    try:
        for rel in stale:
            _delete_path(db, rel, with_vec)
            summary["removed"].append(rel)
        for rel in changed:
            p = corpus_files[rel]
            _delete_path(db, rel, with_vec)
            text = p.read_text(encoding="utf-8", errors="replace")
            seq_offset = int(db.execute("SELECT COALESCE(MAX(seq)+1,0) FROM chunks WHERE path=?", (rel,)).fetchone()[0])
            got = index_one(db, rel, text, seq_offset, cal, with_vec)
            db.execute(
                "INSERT INTO files(path, sha, mtime, bytes) VALUES(?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET sha=excluded.sha, mtime=excluded.mtime, bytes=excluded.bytes",
                (rel, sha256_file(p), p.stat().st_mtime, p.stat().st_size),
            )
            summary["added"].append((rel, got[0]))
            n_chunks += got[0]
            n_chars += got[1]
            n_tokens += got[2]
        db.commit()
    except Exception:
        db.rollback()
        raise

    tok_per_char = None
    if n_chars > 0:
        # LM Studio reports usage 0 for embeddings -> fall back to the measured
        # default constant (1.9 tok/char on this corpus) when no usage arrives.
        tok_per_char = (n_tokens / n_chars) if n_tokens > 0 else cal
        _set_meta(db, "tok_per_char", f"{tok_per_char:.4f}")
    head = "unknown"
    marker_data: dict = {}
    marker = cfg.CORPUS_DIR / ".corpus_source.json"
    try:
        if marker.is_file():
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
            head = str(marker_data.get("source_commit") or "unknown")
    except (OSError, ValueError):
        marker_data = {}
    if head == "unknown":
        try:
            head = subprocess.run(
                ["git", "-C", str(cfg.CORPUS_DIR), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            print(f"warn: git rev-parse failed under {cfg.CORPUS_DIR}", file=sys.stderr)
    _set_meta(db, "last_indexed_ts", f"{int(time.time())}")
    _set_meta(db, "corpus_head", head)
    _set_meta(db, "synced_at", str(marker_data.get("synced_at") or ""))
    _set_meta(db, "dirty", "true" if marker_data.get("dirty") else "false")
    db.commit()

    counts = {
        "files": db.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        "chunks": db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "chars": db.execute("SELECT COALESCE(SUM(LENGTH(text)),0) FROM chunks").fetchone()[0],
        "tokens_est": db.execute("SELECT COALESCE(SUM(est_tokens),0) FROM chunks").fetchone()[0],
    }
    db.close()
    summary.update(counts=counts, changed=len(changed), stale_count=len(stale),
                   cal=round(tok_per_char, 4) if tok_per_char else cal,
                   corpus_head=head,
                   elapsed_s=round(time.time() - started, 2))
    return summary


_LOCK_DIR = None  # 於 __main__ 取得（cfg 依 RAG_CORPUS 而異，故延後建構）
_LOCK_STALE_SECONDS = 1800


def _acquire_index_lock() -> bool:
    """單一索引器鎖：mkdir 原子取得；殘留逾時 30 分自動回收（cron 與手動/鏈觸發並存用）。"""
    global _LOCK_DIR
    _LOCK_DIR = cfg.DATA_DIR / ".index.lock"
    _LOCK_DIR.parent.mkdir(parents=True, exist_ok=True)
    try:
        _LOCK_DIR.mkdir()
        return True
    except FileExistsError:
        try:
            age = time.time() - _LOCK_DIR.stat().st_mtime
        except OSError:
            age = 0.0
        if age <= _LOCK_STALE_SECONDS:
            return False
        try:
            _LOCK_DIR.rmdir()
            _LOCK_DIR.mkdir()
            return True
        except OSError:
            return False


def _release_index_lock() -> None:
    if _LOCK_DIR is not None:
        try:
            _LOCK_DIR.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    if not _acquire_index_lock():
        print("skip: 另一個索引器進行中（.index.lock）")
        raise SystemExit(0)
    try:
        res = run_index()
    finally:
        _release_index_lock()
    print(f"sqlite-vec={res['vec']} changed_files={res['changed']} removed={res['stale_count']}")
    print(f"files={res['counts']['files']} chunks={res['counts']['chunks']} "
          f"chars={res['counts']['chars']} est_tokens={res['counts']['tokens_est']} "
          f"tok_per_char={res['cal']} elapsed={res['elapsed_s']}s corpus_head={res['corpus_head']}")
    for rel, n in res["added"]:
        print(f"  + {rel} ({n} chunks)")
