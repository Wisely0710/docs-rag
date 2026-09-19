"""Answer pipeline: retrieve excerpts, prompt a chat model, extract citations.

The retrieval call is injected (`retriever`), so the pipeline is testable without an
index, and the prompt is plain text — no framework, no hidden state. The model is
instructed to answer only from the excerpts and to cite corpus paths in backticks;
when the excerpts do not contain the answer it must reply with `NOT_IN_CORPUS`
(see qa.llm.ABSTAIN_MARKER).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from qa.llm import ABSTAIN_MARKER, ChatClient, ChatReply, Message

SYSTEM_PROMPT = (
    "You answer questions about a software portfolio, using only the provided documentation "
    "excerpts.\n"
    "Rules:\n"
    "1. Use only the excerpts. Never add outside knowledge.\n"
    "2. Cite the source of every claim with a backticked corpus path, "
    "e.g. `docs/x402-agent-payments/verifier/README.md`.\n"
    f"3. If the excerpts do not contain the answer, reply with {ABSTAIN_MARKER} on the first "
    "line, then at most one short sentence saying what is missing.\n"
    "4. Answer in the language of the question, concisely (at most 150 words)."
)

_CITATION_RE = re.compile(r"`([^`\n]+\.md)`")

Retriever = Callable[[str, int], Sequence[dict[str, Any]]]


@dataclass(frozen=True)
class Answer:
    question: str
    text: str
    abstained: bool
    citations: list[str]
    hits: list[dict[str, Any]]
    reply: ChatReply


def format_context(
    hits: Sequence[dict[str, Any]],
    *,
    max_chunks: int = 6,
    max_chars_per_chunk: int = 1000,
) -> str:
    """Render retrieved chunks as `### <path> (chunk <seq>)` blocks (the citation contract)."""
    blocks: list[str] = []
    for hit in hits[:max_chunks]:
        text = " ".join(str(hit["text"]).split())
        blocks.append(f"### {hit['path']} (chunk {hit['seq']})\n{text[:max_chars_per_chunk]}")
    return "\n\n".join(blocks)


def build_messages(
    question: str,
    hits: Sequence[dict[str, Any]],
    *,
    max_chunks: int = 6,
    max_chars_per_chunk: int = 1000,
) -> list[Message]:
    context = format_context(hits, max_chunks=max_chunks, max_chars_per_chunk=max_chars_per_chunk)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Question: {question}\n\nDocumentation excerpts:\n\n{context}"},
    ]


def extract_citations(text: str) -> list[str]:
    """Corpus paths cited in backticks, in order of first appearance (duplicates dropped).

    Tokens that cannot be corpus paths (glob or placeholder syntax such as `*.md` or
    `<corpus_dir>/docs/<name>`) are skipped: those are quotations, not citations.
    """
    citations: list[str] = []
    for match in _CITATION_RE.finditer(text):
        path = match.group(1).strip().lstrip("./")
        if not path or any(char in path for char in "*?<>") or path in citations:
            continue
        citations.append(path)
    return citations


def is_abstention(text: str) -> bool:
    """True when the first non-empty line carries the marker (the prompt's contract).

    A model that answers part of the question and only then appends the marker did not
    abstain — that is a partial answer, and the judges score it as one.
    """
    for line in text.splitlines():
        if line.strip():
            return ABSTAIN_MARKER in line
    return False


def answer_question(
    question: str,
    *,
    retriever: Retriever,
    client: ChatClient,
    k: int = 6,
    max_tokens: int = 400,
    temperature: float = 0.0,
    max_chunks: int = 6,
    max_chars_per_chunk: int = 1000,
) -> Answer:
    hits = list(retriever(question, k))
    messages = build_messages(question, hits, max_chunks=max_chunks, max_chars_per_chunk=max_chars_per_chunk)
    reply = client.chat(messages, temperature=temperature, max_tokens=max_tokens)
    return Answer(
        question=question,
        text=reply.text,
        abstained=is_abstention(reply.text),
        citations=extract_citations(reply.text),
        hits=hits,
        reply=reply,
    )
