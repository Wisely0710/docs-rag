"""Unit tests for the judging and aggregation logic (verdict parsing, kappa, metrics, labels)."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from eval.qa.run_qa_eval import aggregate, cohen_kappa, load_golden_qa, safe_answer
from qa.judge import JudgeParseError, judge_answer, parse_judgment
from qa.llm import ABSTAIN_MARKER, ChatError, StubClient


def test_parse_judgment_accepts_fenced_and_embedded_json() -> None:
    fenced = '```json\n{"verdict": "Correct.", "unsupported_claims": [], "rationale": "ok"}\n```'
    assert parse_judgment(fenced) == ("correct", [], "ok")
    embedded = 'Here: {"verdict": "partial", "unsupported_claims": ["42"], "rationale": "meh"} — done.'
    assert parse_judgment(embedded) == ("partial", ["42"], "meh")


@pytest.mark.parametrize(
    "reply",
    [
        "no json at all",
        '{"verdict": "maybe", "unsupported_claims": [], "rationale": "x"}',
        '{"verdict": "correct", "unsupported_claims": "nope", "rationale": "x"}',
    ],
)
def test_parse_judgment_rejects_unusable_replies(reply: str) -> None:
    with pytest.raises(JudgeParseError):
        parse_judgment(reply)


def test_judge_stub_grades_abstention_on_unanswerable_rows() -> None:
    client = StubClient()
    refused = judge_answer(
        "Which cloud provider hosts it?",
        f"{ABSTAIN_MARKER} — the documents do not cover deployment.",
        reference="",
        context="unrelated excerpts",
        unanswerable=True,
        client=client,
    )
    assert refused.verdict == "correct"

    fabricated = judge_answer(
        "Which cloud provider hosts it?",
        "It runs on the example cloud for 40 dollars per month.",
        reference="",
        context="unrelated excerpts",
        unanswerable=True,
        client=client,
    )
    assert fabricated.verdict == "incorrect"


def test_cohen_kappa_handles_agreement_edges() -> None:
    assert cohen_kappa([]) is None
    assert cohen_kappa([("correct", "correct"), ("partial", "partial")]) == 1.0
    # two raters, 4 rows, observed agreement 0.75, expected 0.3125 -> 0.6364
    assert cohen_kappa([("correct", "correct"), ("correct", "partial"), ("incorrect", "incorrect"), ("partial", "partial")]) == 0.6364


def _row(
    row_id: str,
    *,
    unanswerable: bool = False,
    verdict1: str | None = "correct",
    verdict2: str | None = "correct",
    abstained: bool = False,
    citations: list[str] | None = None,
    valid: list[str] | None = None,
    retrieved: list[str] | None = None,
    retrieval_hit: bool | None = True,
    answer_error: str | None = None,
) -> dict[str, Any]:
    def judge(verdict: str | None) -> dict[str, Any]:
        return {
            "verdict": verdict,
            "rationale": "r",
            "unsupported_claims": [],
            "error": None,
            "configured": True,
            "latency_ms": 1.0,
            "prompt_tokens": 10,
            "completion_tokens": 5,
        }

    return {
        "id": row_id,
        "family": "en",
        "question": "q",
        "unanswerable": unanswerable,
        "retrieval_hit": retrieval_hit,
        "retrieval_rank": 1 if retrieval_hit else 0,
        "citations": citations or [],
        "citations_valid": valid or [],
        "citations_retrieved": retrieved or [],
        "abstained": abstained,
        "answer_error": answer_error,
        "answer_latency_ms": 10.0,
        "answer_prompt_tokens": 100,
        "answer_completion_tokens": 10,
        "judge1": judge(verdict1),
        "judge2": judge(verdict2),
    }


def test_aggregate_counts_accuracy_abstention_citations_and_agreement() -> None:
    rows = [
        _row("a", citations=["docs/a.md"], valid=["docs/a.md"], retrieved=["docs/a.md"]),
        _row(
            "b",
            verdict1="incorrect",
            verdict2="incorrect",
            citations=["docs/ghost.md"],
            retrieval_hit=False,
        ),
        _row("c", verdict1="partial", verdict2="partial"),
        _row("d", unanswerable=True, abstained=True, retrieval_hit=None),
        _row("e", unanswerable=True, verdict1="incorrect", abstained=False, retrieval_hit=None),
        _row("f", verdict1=None, verdict2=None, answer_error="chat failed: truncated"),
    ]
    metrics = aggregate(rows)
    assert metrics["answer_failures"] == 1
    assert metrics["answerable"] == 4
    assert metrics["unanswerable"] == 2
    assert metrics["answer_accuracy_primary"] == 0.3333
    assert metrics["answer_accuracy_primary_lenient"] == 0.6667
    assert metrics["answer_accuracy_secondary"] == 0.3333
    assert metrics["abstention_on_unanswerable_marker"] == 0.5
    assert metrics["abstention_on_unanswerable_primary"] == 0.5
    assert metrics["over_abstention_answerable"] == 0.0
    assert metrics["retrieval_hit_at_k"] == 0.75
    assert metrics["citations"]["citation_paths_valid"] == 0.5
    assert metrics["citations"]["citation_paths_retrieved"] == 0.5
    assert metrics["judge_agreement"]["rows"] == 5
    assert metrics["judge_agreement"]["agreement"] == 0.8
    assert metrics["judge_agreement"]["kappa"] == 0.6875
    assert metrics["tokens"]["answer"]["prompt"] == 600


def test_load_golden_requires_reference_for_answerable_rows(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "golden.jsonl"
    path.write_text(json.dumps({"id": "x", "question": "q"}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_golden_qa(path)


def test_safe_answer_records_chat_failures_instead_of_raising() -> None:
    class ExplodingClient:
        backend = "boom"
        model = "boom"

        def chat(self, messages: object, *, temperature: float = 0.0, max_tokens: int = 500) -> object:
            raise ChatError("returned only reasoning_content")

    answer, error = safe_answer("q", [], client=ExplodingClient(), k=3, max_tokens=100)
    assert answer is None
    assert error is not None
    assert "reasoning_content" in error


def test_load_golden_accepts_unanswerable_rows(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "golden.jsonl"
    rows = [
        {"id": "a", "family": "en", "question": "q", "reference": "r", "expected_docs": ["docs/a.md"]},
        {"id": "b", "family": "zh", "question": "q2", "unanswerable": True},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    loaded = load_golden_qa(path)
    assert loaded[1]["unanswerable"] is True
    assert loaded[1]["reference"] == ""
    assert loaded[1]["expected_docs"] == []
