"""Corpus discovery, hashing and chunking for the per-project docs RAG indexer."""
from __future__ import annotations

import hashlib
import pathlib
import re

import ragconfig as cfg

_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_FRONTMATTER_RE = re.compile(r"^---[^\n]*\n.*?\n---\s*\n", re.DOTALL)


def iter_corpus_files() -> list[pathlib.Path]:
    """AGENTS.md + docs/ root md files + md files under the configured corpus trees."""
    files: list[pathlib.Path] = []
    for rel in cfg.CORPUS_TOP_FILES:
        p = cfg.CORPUS_DIR / rel
        if p.is_file():
            files.append(p)
    for name in cfg.CORPUS_DOC_ROOT_FILES:
        p = cfg.CORPUS_DIR / "docs" / name
        if p.is_file():
            files.append(p)
    for rel in cfg.CORPUS_ROOTS:
        root = cfg.CORPUS_DIR / rel
        if root.is_dir():
            for p in sorted(root.rglob("*.md")):
                rel_parts = p.relative_to(cfg.CORPUS_DIR).parts
                if not any(part in cfg.CORPUS_EXCLUDE_DIRS for part in rel_parts):
                    files.append(p)
    return files


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _drop_frontmatter(text: str) -> str:
    if text.startswith("---"):
        text = _FRONTMATTER_RE.sub("", text, count=1)
    return text


def chunk_markdown(text: str, min_chars: int, max_chars: int, overlap_chars: int) -> list[str]:
    """Section-aware chunking.

    - paragraphs (blank-line separated line groups) are atomic units;
    - markdown headings start new sections;
    - sections under `min_chars` merge with following ones;
    - oversized sections are split on line boundaries with a sliding overlap.
    """
    text = _drop_frontmatter(text).replace("\r\n", "\n")
    segs: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if buf:
                segs.append("\n".join(buf))
                buf = []
            continue
        if _HEADING_RE.match(line):
            if buf:
                segs.append("\n".join(buf))
                buf = []
            segs.append(line.strip())
        else:
            buf.append(line)
    if buf:
        segs.append("\n".join(buf))

    chunks: list[str] = []
    acc = ""
    for seg in segs:
        if len(seg) > max_chars:
            if acc:
                chunks.append(acc)
                acc = ""
            start = 0
            seg_len = len(seg)
            while start < seg_len:
                end = min(start + max_chars, seg_len)
                cut = seg.rfind("\n", start + max_chars // 2, end)
                if cut > start:
                    end = cut + 1
                piece = seg[start:end]
                chunks.append(piece)
                if end >= seg_len:
                    break
                start = max(end - overlap_chars, start + 1)
                # keep the overlap aligned on a line start when possible
                nl = seg.find("\n", start)
                if 0 <= nl < start + overlap_chars:
                    start = nl + 1
            continue
        candidate = seg if not acc else acc + "\n\n" + seg
        if len(candidate) <= max_chars:
            acc = candidate
        else:
            chunks.append(acc)
            acc = seg
    if acc:
        chunks.append(acc)

    kept = [c for c in chunks if len(c) >= min(min_chars, 120)]
    return kept if kept else chunks


def relpath_of(path: pathlib.Path) -> str:
    return str(path.relative_to(cfg.CORPUS_DIR))
