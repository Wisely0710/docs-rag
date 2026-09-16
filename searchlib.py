"""Hybrid retrieval: sqlite-vec (or numpy fallback) + FTS5 trigram, RRF merge."""
from __future__ import annotations

import datetime
import math
import os
import re
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any

from ragconfig import DB_PATH, EMBED_DIM, embed_texts

_RRF_K = 60
_NP: Any = None
_QUERY_LOG_DIR = Path(__file__).resolve().parent / "logs"


def log_query(
    tool: str,
    *,
    caller: str = "direct",
    query: str = "",
    k: int | None = None,
    hits: int | None = None,
    ms: float | None = None,
) -> None:
    """查詢級計量：一行一呼叫（tool／caller／k／hits／latency／query 前 200 字）。

    落 `logs/queries-<RAG_CORPUS|default>.log`（per-corpus，不與其他語料混檔）。
    best-effort：寫入失敗（權限／磁碟）一律靜默略過——RAG 為定位工具，計量不得影響檢索。
    """
    try:
        corpus = os.environ.get("RAG_CORPUS", "default")
        parts = [
            f"ts={datetime.datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"caller={caller}",
            f"tool={tool}",
        ]
        if k is not None:
            parts.append(f"k={k}")
        if hits is not None:
            parts.append(f"hits={hits}")
        if ms is not None:
            parts.append(f"ms={ms:.0f}")
        if query:
            parts.append('query="' + " ".join(query.split())[:200] + '"')
        _QUERY_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_QUERY_LOG_DIR / f"queries-{corpus}.log", "a", encoding="utf-8") as fh:
            fh.write("\t".join(parts) + "\n")
    except OSError:
        pass


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _vec_ok(db: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec  # type: ignore

        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        db.execute("SELECT 1 FROM vec_chunks LIMIT 0").fetchall()
        return True
    except (ImportError, OSError, sqlite3.Error):
        return False


def _connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA query_only=ON")
    return db


def _vector_top(db: sqlite3.Connection, qvec: list[float], n: int) -> list[tuple[int, float]]:
    if _vec_ok(db):
        blob = struct.pack(f"<{EMBED_DIM}f", *qvec)
        return [
            (rowid, dist)
            for rowid, dist in db.execute(
                "SELECT rowid, distance FROM vec_chunks WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (blob, n),
            )
        ]
    # numpy brute-force fallback (corpus is small: <10k chunks)
    import numpy as np  # type: ignore

    global _NP
    sig = db.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM chunks").fetchone()
    if _NP is None or _NP[0] != sig:
        rows = db.execute("SELECT id, vec FROM chunks WHERE vec IS NOT NULL").fetchall()
        if not rows:
            _NP = (sig, [], np.zeros((0, EMBED_DIM), dtype=np.float32))
            return []
        ids = [r[0] for r in rows]
        arr = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(-1, EMBED_DIM)
        _NP = (sig, ids, arr)
    _, ids, arr = _NP
    if not ids:
        return []
    dots = arr @ np.asarray(qvec, dtype=np.float32)
    top = np.argpartition(-dots, min(n, len(ids) - 1))[:n]
    top = top[np.argsort(-dots[top])]
    return [(ids[i], float(1.0 - dots[i])) for i in top]


def _clean_query(query: str) -> str:
    words = [w for w in re.findall(r"[\w\u4e00-\u9fff]+", query.lower()) if len(w) >= 3]
    return " ".join(words)


def _fts_top(db: sqlite3.Connection, query: str, n: int) -> list[int]:
    cleaned = _clean_query(query)
    if not cleaned:
        return []
    try:
        rows = db.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
            (cleaned, n),
        ).fetchall()
        return [r[0] for r in rows]
    except sqlite3.OperationalError:
        # degenerate tokenization; try the single longest run
        runs = re.findall(r"[\w\u4e00-\u9fff]{3,}", query.lower())
        for run in sorted(set(runs), key=len, reverse=True):
            try:
                rows = db.execute(
                    "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                    (run, n),
                ).fetchall()
                return [r[0] for r in rows]
            except sqlite3.OperationalError:
                continue
    return []


def retrieve(query: str, k: int = 5, caller: str = "direct") -> list[dict]:
    """Return up to k dicts: {path, seq, text, score} ranked by RRF over vector+FTS.

    每次呼叫記一行查詢計量（`log_query`；best-effort，失敗不影響結果）。
    """
    started = time.monotonic()
    k = max(1, min(int(k), 10))
    qvec = embed_texts([query])[0][0]
    qvec = _norm(qvec)
    pool = max(15, k * 4)

    db = _connect()
    try:
        vt = _vector_top(db, qvec, pool)
        ft = _fts_top(db, query, pool)
        scores: dict[int, float] = {}
        for rank, (rowid, _dist) in enumerate(vt):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        for rank, rowid in enumerate(ft):
            scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        if not ranked:
            return []
        qmarks = ",".join("?" * len(ranked))
        rows = {
            rid: (path, seq, text)
            for rid, path, seq, text in db.execute(
                f"SELECT id, path, seq, text FROM chunks WHERE id IN ({qmarks})",
                [rid for rid, _ in ranked],
            )
        }
        out = []
        seen = set()
        for rid, score in ranked:
            row = rows.get(rid)
            if not row:
                continue
            key = (row[0], row[1])
            if key in seen:
                continue
            seen.add(key)
            out.append({"path": row[0], "seq": row[1], "text": row[2], "score": round(score, 5)})
        return out
    finally:
        _hits = len(out) if "out" in locals() else 0  # 早退（無結果）路徑無 out → 0
        log_query("retrieve", caller=caller, query=query, k=k, hits=_hits, ms=(time.monotonic() - started) * 1000)
        db.close()


def corpus_stats() -> dict:
    db = _connect()
    try:
        meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
        counts = {
            "files": db.execute("SELECT COUNT(*) FROM files").fetchone()[0],
            "chunks": db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        }
        return {
            **counts,
            "last_indexed_ts": meta.get("last_indexed_ts"),
            "corpus_head": meta.get("corpus_head"),
            "synced_at": meta.get("synced_at"),
            "dirty": meta.get("dirty") == "true",
        }
    finally:
        db.close()
