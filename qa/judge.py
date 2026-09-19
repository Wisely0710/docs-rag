"""LLM-as-judge for the answer-quality harness: verdict + unsupported claims + rationale.

The judge sees the question, the reference answer, the retrieved excerpts and the
candidate answer, and returns JSON only. Deliberately the same two-message surface as
the answer pipeline, so any OpenAI-compatible endpoint (or the offline stub) can judge.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, cast

from qa.llm import ChatClient, ChatReply, Message

Verdict = Literal["correct", "partial", "incorrect"]
_VERDICTS = ("correct", "partial", "incorrect")

JUDGE_SYSTEM = (
    "You grade a documentation QA system. You are given a question, a reference answer, the "
    "retrieved documentation excerpts the system saw, and its candidate answer.\n"
    'Return JSON only, exactly: {"verdict": "correct|partial|incorrect", '
    '"unsupported_claims": ["..."], "rationale": "..."}\n'
    "Rules: correct = the candidate conveys the key facts of the reference answer and does not "
    "contradict it; partial = some key facts are present but the answer is incomplete or vague; "
    "incorrect = key facts are missing, contradicted, or fabricated.\n"
    "unsupported_claims lists factual claims in the candidate that neither the excerpts nor the "
    "reference support (numbers and names especially); use an empty list when there are none.\n"
    "rationale: at most 40 words, no markdown."
)

JUDGE_SYSTEM_UNANSWERABLE = (
    "You grade a documentation QA system. The question is deliberately outside the corpus: the "
    "documents do not contain the answer, so the correct behaviour is to decline.\n"
    'Return JSON only, exactly: {"verdict": "correct|partial|incorrect", '
    '"unsupported_claims": ["..."], "rationale": "..."}\n'
    "Rules: correct = the candidate says it cannot answer from the corpus (or states that the "
    "documents do not cover it) and asserts no facts; partial = it declines but adds guesses; "
    "incorrect = it asserts facts as if they came from the corpus, or invents sources.\n"
    "unsupported_claims lists any facts the candidate asserted anyway.\n"
    "rationale: at most 40 words, no markdown."
)


class JudgeParseError(ValueError):
    """The judge reply did not contain a usable verdict (raw reply attached for diagnosis)."""

    def __init__(self, message: str, *, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


@dataclass(frozen=True)
class Judgment:
    verdict: Verdict
    unsupported_claims: list[str]
    rationale: str
    raw: str
    reply: ChatReply


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        payload = json.loads(candidate)
    except ValueError:
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if not match:
            raise JudgeParseError("no JSON object in the judge reply", raw=text) from None
        try:
            payload = json.loads(match.group(0))
        except ValueError as exc:
            raise JudgeParseError(f"judge reply is not valid JSON: {exc}", raw=text) from exc
    if not isinstance(payload, dict):
        raise JudgeParseError("judge reply is not a JSON object", raw=text)
    return payload


def parse_judgment(text: str) -> tuple[Verdict, list[str], str]:
    payload = _extract_json_object(text)
    verdict = str(payload.get("verdict", "")).strip().lower().rstrip(".")
    if verdict not in _VERDICTS:
        raise JudgeParseError(f"unknown verdict {payload.get('verdict')!r} in the judge reply", raw=text)
    claims = payload.get("unsupported_claims") or []
    if not isinstance(claims, list):
        raise JudgeParseError("unsupported_claims is not a list", raw=text)
    rationale = " ".join(str(payload.get("rationale", "")).split())
    return cast(Verdict, verdict), [str(claim) for claim in claims], rationale


def build_judge_messages(
    question: str,
    candidate: str,
    *,
    reference: str,
    context: str,
    unanswerable: bool,
) -> list[Message]:
    system = JUDGE_SYSTEM_UNANSWERABLE if unanswerable else JUDGE_SYSTEM
    reference_line = "" if unanswerable else f"Reference answer: {reference}\n\n"
    user = (
        f"Question: {question}\n\n"
        f"{reference_line}"
        f"Retrieved excerpts:\n\n{context}\n\n"
        f"Candidate answer:\n{candidate}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def judge_answer(
    question: str,
    candidate: str,
    *,
    reference: str,
    context: str,
    unanswerable: bool,
    client: ChatClient,
    max_tokens: int = 300,
    temperature: float = 0.0,
) -> Judgment:
    messages = build_judge_messages(
        question, candidate, reference=reference, context=context, unanswerable=unanswerable
    )
    reply = client.chat(messages, temperature=temperature, max_tokens=max_tokens)
    verdict, claims, rationale = parse_judgment(reply.text)
    return Judgment(
        verdict=verdict,
        unsupported_claims=claims,
        rationale=rationale,
        raw=reply.text,
        reply=reply,
    )
