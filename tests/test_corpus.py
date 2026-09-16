"""Unit tests for corpus discovery and chunking (pure functions + cfg-driven scan)."""

from __future__ import annotations

import pathlib

import corpus


def test_drop_frontmatter_strips_leading_block_only():
    assert corpus._drop_frontmatter("---\ntitle: x\n---\nbody") == "body"
    assert corpus._drop_frontmatter("no frontmatter here") == "no frontmatter here"
    # a later '---' rule must survive
    assert corpus._drop_frontmatter("intro\n\n---\n\noutro") == "intro\n\n---\n\noutro"


def test_chunk_markdown_merges_sections_until_budget():
    chunks = corpus.chunk_markdown("# A\nfirst\n\n# B\nsecond", min_chars=1, max_chars=20, overlap_chars=5)
    assert chunks == ["# A\n\nfirst\n\n# B", "second"]


def test_chunk_markdown_splits_oversized_section_within_budget():
    text = "line1\nline2\nline3\nline4"
    chunks = corpus.chunk_markdown(text, min_chars=1, max_chars=12, overlap_chars=3)
    assert len(chunks) == 2
    assert all(len(chunk) <= 12 for chunk in chunks)
    assert chunks[0].endswith("line2\n") and "line3" in chunks[1]


def test_chunk_markdown_never_returns_empty_for_short_text():
    # below min_chars the filter would drop everything; the fallback must keep the text
    chunks = corpus.chunk_markdown("tiny", min_chars=1000, max_chars=2000, overlap_chars=5)
    assert chunks == ["tiny"]


def test_chunk_markdown_normalizes_crlf():
    chunks = corpus.chunk_markdown("a\r\n\r\nb", min_chars=1, max_chars=100, overlap_chars=5)
    assert chunks == ["a\n\nb"] and "\r" not in chunks[0]


def test_iter_corpus_files_scope_and_exclusions(tmp_path: pathlib.Path, monkeypatch) -> None:
    (tmp_path / "AGENTS.md").write_text("top", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not markdown", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("doc root", encoding="utf-8")
    (tmp_path / "docs" / "notes").mkdir()
    (tmp_path / "docs" / "notes" / "keep.md").write_text("keep", encoding="utf-8")
    (tmp_path / "docs" / "notes" / "archive").mkdir()
    (tmp_path / "docs" / "notes" / "archive" / "old.md").write_text("old", encoding="utf-8")

    monkeypatch.setattr(corpus.cfg, "CORPUS_DIR", tmp_path)
    monkeypatch.setattr(corpus.cfg, "CORPUS_TOP_FILES", ["AGENTS.md", "MISSING.md"])
    monkeypatch.setattr(corpus.cfg, "CORPUS_DOC_ROOT_FILES", ["README.md"])
    monkeypatch.setattr(corpus.cfg, "CORPUS_ROOTS", ["docs/notes", "docs/absent"])
    monkeypatch.setattr(corpus.cfg, "CORPUS_EXCLUDE_DIRS", ("archive",))

    found = sorted(corpus.relpath_of(path) for path in corpus.iter_corpus_files())

    # doc_root_files resolve under docs/; roots recurse; archive/ and non-md are out;
    # missing entries are skipped rather than raising.
    assert found == ["AGENTS.md", "docs/README.md", "docs/notes/keep.md"]
