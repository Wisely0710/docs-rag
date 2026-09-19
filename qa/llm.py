"""Minimal OpenAI-compatible chat client for the QA layer (no SDK dependency, like the embedder).

Backends:

    deepseek  — the official DeepSeek API; key from DEEPSEEK_API_KEY, base overridable
                via DEEPSEEK_BASE_URL (default https://api.deepseek.com/v1)
    lmstudio  — a local LM Studio server (LMSTUDIO_BASE_URL / LMSTUDIO_API_KEY, the
                same environment the embedding backend already uses)
    stub      — deterministic, offline replies for tests, the demo and CI

Both real backends expose the same two-field surface: POST {base_url}/chat/completions
with {model, messages}. Nothing else is needed, so the repo stays dependency-light.

ABSTAIN_MARKER is part of the QA protocol: the answer prompt demands it when the
excerpts do not contain the answer, the judges treat it as the abstention signal, and
the offline stub emits it — hence it lives here, shared by all three.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

Message = dict[str, str]
ABSTAIN_MARKER = "NOT_IN_CORPUS"

_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_WORD_RE = re.compile(r"[0-9a-z]{4,}")


class ChatError(RuntimeError):
    """A chat call failed (after retries, or with a non-retryable response)."""


@dataclass(frozen=True)
class ChatReply:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float


class ChatClient(Protocol):
    backend: str
    model: str

    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> ChatReply: ...


def _post_json(url: str, payload: dict[str, Any], api_key: str, timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class OpenAICompatibleClient:
    """Chat over ``{base_url}/chat/completions`` (DeepSeek or LM Studio)."""

    def __init__(self, *, backend: str, base_url: str, api_key: str, model: str, timeout: float = 180.0) -> None:
        self.backend = backend
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> ChatReply:
        payload = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        started = time.perf_counter()
        body: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                body = _post_json(f"{self.base_url}/chat/completions", payload, self.api_key, self.timeout)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in _RETRY_STATUS:
                    raise ChatError(f"{self.backend} chat failed: HTTP {exc.code} {exc.reason}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
            if body is not None:
                break
            if attempt + 1 < _MAX_ATTEMPTS:
                time.sleep(1.5 * (attempt + 1))
        if body is None:
            raise ChatError(f"{self.backend} chat failed after {_MAX_ATTEMPTS} attempts: {last_error}")

        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ChatError(f"{self.backend} chat returned an unexpected body: {str(body)[:200]}") from exc
        text = str(message.get("content") or "")
        if not text and message.get("reasoning_content"):
            raise ChatError(
                f"{self.backend} model {self.model} returned only reasoning_content — "
                "a reasoning model needs a larger max_tokens"
            )
        usage = body.get("usage") or {}
        return ChatReply(
            text=text.strip(),
            model=str(body.get("model") or self.model),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )


class StubClient:
    """Deterministic offline replies — mechanics only, no model and no network.

    Answers: like a minimal extractive reader — if the question shares no word with the
    excerpts it abstains, otherwise it returns the first sentence of the top-ranked
    excerpt and cites that excerpt's path. Judging: a fixed verdict, except that the
    unanswerable prompt is graded on whether the candidate abstained. The metrics a stub
    run produces therefore check the harness plumbing, not answer quality (the same
    contract as the stub embedding backend).
    """

    backend = "stub"

    def __init__(self, model: str = "stub") -> None:
        self.model = model

    def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int = 500,
    ) -> ChatReply:
        started = time.perf_counter()
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if messages else ""
        text = self._reply(system, user)
        return ChatReply(
            text=text,
            model=self.model,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    @staticmethod
    def _reply(system: str, user: str) -> str:
        if '"verdict"' in system:
            candidate = user.split("Candidate answer:", 1)[-1]
            if "outside the corpus" in system:
                verdict = "correct" if ABSTAIN_MARKER in candidate else "incorrect"
                rationale = "stub: candidate abstained" if verdict == "correct" else "stub: candidate answered"
            else:
                verdict, rationale = "correct", "stub backend: no judgement performed"
            return json.dumps({"verdict": verdict, "unsupported_claims": [], "rationale": rationale})

        block = re.search(r"^###\s+(\S+\.md)\s+\(chunk \d+\)\s*\n+(.*)$", user, re.MULTILINE)
        if not block:
            return f"{ABSTAIN_MARKER}\nstub backend: no excerpts were provided"
        question = user.split("Question:", 1)[-1].split("\n", 1)[0]
        context = user.split("Documentation excerpts:", 1)[-1]
        if not set(_WORD_RE.findall(question.lower())) & set(_WORD_RE.findall(context.lower())):
            return f"{ABSTAIN_MARKER}\nstub backend: no lexical overlap with the excerpts"
        first_line = block.group(2).strip().split("\n", 1)[0]
        sentence = re.split(r"(?<=[.!?。！？])\s*", first_line)[0][:200]
        return f"According to `{block.group(1)}`: {sentence}"


def make_client(backend: str, model: str | None = None) -> ChatClient:
    """Build a chat client; keys and base URLs come from the environment (RAG_DIR/.env is loaded)."""
    if backend == "stub":
        return StubClient(model or "stub")
    if backend == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise ChatError("DEEPSEEK_API_KEY is not set (environment or RAG_DIR/.env)")
        base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        return OpenAICompatibleClient(
            backend="deepseek", base_url=base, api_key=api_key, model=model or "deepseek-flash"
        )
    if backend == "lmstudio":
        if not model:
            raise ChatError("--model is required for the lmstudio backend (local models are deployment data)")
        base = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
        return OpenAICompatibleClient(
            backend="lmstudio", base_url=base, api_key=os.environ.get("LMSTUDIO_API_KEY", ""), model=model
        )
    raise ChatError(f"unknown chat backend {backend!r} (expected stub, deepseek or lmstudio)")
