"""Unit tests for the answer pipeline (prompt, citations, stub client) — no network."""

from __future__ import annotations

from typing import Any

from qa.answer import answer_question, build_messages, extract_citations, format_context, is_abstention
from qa.llm import ABSTAIN_MARKER, StubClient


def _hits() -> list[dict[str, Any]]:
    return [
        {
            "path": "docs/demo/verifier.md",
            "seq": 2,
            "text": "The verifier never custodies keys. Settlement happens later.",
            "score": 0.5,
        },
        {
            "path": "docs/demo/client.md",
            "seq": 1,
            "text": "The browser client signs with the injected wallet.",
            "score": 0.4,
        },
    ]


def test_build_messages_includes_question_context_and_rules() -> None:
    messages = build_messages("Who holds keys?", _hits())
    assert messages[0]["role"] == "system"
    assert ABSTAIN_MARKER in messages[0]["content"]
    user = messages[1]["content"]
    assert "Who holds keys?" in user
    assert "### docs/demo/verifier.md (chunk 2)" in user
    assert "never custodies keys" in user


def test_format_context_applies_chunk_and_length_limits() -> None:
    hits = [{"path": f"docs/doc-{index}.md", "seq": index, "text": "x" * 50, "score": 0.1} for index in range(8)]
    context = format_context(hits, max_chunks=2, max_chars_per_chunk=10)
    assert context.count("###") == 2
    assert "x" * 10 in context
    assert "x" * 11 not in context


def test_extract_citations_deduplicates_and_ignores_non_paths() -> None:
    text = "See `docs/a.md`, `./docs/b.md` and `docs/a.md`; not `main.py` or `*.md` or `<corpus_dir>/docs/<name>.md`."
    assert extract_citations(text) == ["docs/a.md", "docs/b.md"]


def test_answer_question_passes_k_and_uses_the_stub_citation() -> None:
    calls: list[tuple[str, int]] = []

    def retriever(question: str, k: int) -> list[dict[str, Any]]:
        calls.append((question, k))
        return _hits()

    answer = answer_question("Who holds keys?", retriever=retriever, client=StubClient(), k=3)
    assert calls == [("Who holds keys?", 3)]
    assert answer.citations == ["docs/demo/verifier.md"]
    assert not answer.abstained
    assert answer.text.startswith("According to `docs/demo/verifier.md`")

    refused = answer_question("What is the capital of France?", retriever=retriever, client=StubClient())
    assert refused.abstained
    assert refused.citations == []


def test_abstention_requires_the_marker_on_the_first_line() -> None:
    assert is_abstention(f"{ABSTAIN_MARKER}\nnothing in the docs")
    assert is_abstention(f"**{ABSTAIN_MARKER}** — not covered")
    assert not is_abstention(f"The docs cover A.\n{ABSTAIN_MARKER} — but not B.")
    assert not is_abstention("")


def test_stub_client_is_deterministic_and_abstains_without_excerpts() -> None:
    messages = build_messages("Who holds keys?", _hits())
    client = StubClient()
    assert client.chat(messages).text == client.chat(messages).text

    answer = answer_question("Who holds keys?", retriever=lambda _question, _k: [], client=client)
    assert answer.abstained
    assert answer.citations == []
