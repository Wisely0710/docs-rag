"""Exposure policy: loopback by default, token required off-loopback, guard on requests.

The guard is driven over raw ASGI (no httpx/TestClient in this environment), with a
trivial inner app, so the assertions are about the contract the MCP app depends on:
unauthorised HTTP requests never reach the wrapped app.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from netguard import BearerTokenGuard, UnsafeBindingError, resolve_binding, security_settings


def _call(app: Any, headers: list[tuple[bytes, bytes]], scope_type: str = "http") -> tuple[list[dict[str, Any]], bool]:
    """Drive an ASGI app once; returns (sent messages, inner app was reached)."""
    sent: list[dict[str, Any]] = []
    reached = False

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    inner_holder: dict[str, Any] = {}

    async def inner(scope: dict[str, Any], receive_: Any, send_: Any) -> None:
        inner_holder["reached"] = True
        await send_({"type": "http.response.start", "status": 200, "headers": []})
        await send_({"type": "http.response.body", "body": b"ok"})

    app_with_inner = app(inner)
    scope = {"type": scope_type, "headers": headers, "method": "POST", "path": "/mcp"}
    asyncio.run(app_with_inner(scope, receive, send))
    reached = bool(inner_holder.get("reached"))
    return sent, reached


def test_resolve_binding_defaults_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_HOST", raising=False)
    monkeypatch.delenv("RAG_AUTH_TOKEN", raising=False)
    assert resolve_binding() == ("127.0.0.1", "")


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "10.0.0.5", "corpus.internal"])
def test_non_loopback_binding_without_token_is_refused(host: str) -> None:
    with pytest.raises(UnsafeBindingError, match="RAG_AUTH_TOKEN"):
        resolve_binding(host, "")


def test_non_loopback_binding_with_token_is_allowed() -> None:
    assert resolve_binding("0.0.0.0", "s3cret") == ("0.0.0.0", "s3cret")


def test_empty_host_is_refused() -> None:
    with pytest.raises(UnsafeBindingError):
        resolve_binding("  ", "s3cret")


def test_security_settings_enable_host_and_origin_validation() -> None:
    loopback = security_settings("127.0.0.1", 8765)
    assert loopback.enable_dns_rebinding_protection is True
    assert "localhost:*" in loopback.allowed_hosts

    exposed = security_settings("0.0.0.0", 8765)
    assert exposed.enable_dns_rebinding_protection is True
    assert "0.0.0.0:8765" in exposed.allowed_hosts
    assert "http://0.0.0.0:8765" in exposed.allowed_origins


def test_guard_denies_missing_and_wrong_tokens_without_reaching_the_app() -> None:
    sent, reached = _call(lambda inner: BearerTokenGuard(inner, "s3cret"), [])
    assert sent[0]["status"] == 401
    assert reached is False

    sent, reached = _call(lambda inner: BearerTokenGuard(inner, "s3cret"), [(b"authorization", b"Bearer nope")])
    assert sent[0]["status"] == 401
    assert reached is False


def test_guard_accepts_the_configured_token() -> None:
    sent, reached = _call(lambda inner: BearerTokenGuard(inner, "s3cret"), [(b"authorization", b"Bearer s3cret")])
    assert sent[0]["status"] == 200
    assert reached is True


def test_guard_passes_non_http_scopes_through() -> None:
    sent, reached = _call(lambda inner: BearerTokenGuard(inner, "s3cret"), [], scope_type="lifespan")
    assert reached is True
    assert sent and sent[0]["status"] == 200
