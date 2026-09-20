"""Transport binding and access policy for the HTTP transports — fail closed by default.

The MCP endpoint carries no caller identity: whoever can reach the port can list the
tools and read the whole corpus. This deployment therefore refuses to expose itself by
accident:

- the default bind is loopback (``127.0.0.1``), not every interface;
- binding a non-loopback host requires a bearer token (``RAG_AUTH_TOKEN``), or the
  process refuses to start;
- Host/Origin (DNS-rebinding) validation is enabled on every HTTP transport instead of
  relying on the SDK default, which only turns it on when the host is loopback.

The token check is a plain shared-secret gate for a trusted-network deployment, not an
OAuth resource server: it is deliberately not modelled as MCP ``AuthSettings`` (that
would advertise OAuth discovery for an endpoint that has no authorization server).
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
ASGIApp = Callable[[Scope, Callable[[], Awaitable[Message]], Callable[[Message], Awaitable[None]]], Awaitable[None]]

_UNAUTHORIZED_BODY = b'{"error":"unauthorized"}'
_WWW_AUTHENTICATE = b"Bearer"


class UnsafeBindingError(RuntimeError):
    """Raised when the configured binding would expose the corpus without a token."""


def resolve_binding(host: str | None = None, token: str | None = None) -> tuple[str, str]:
    """Return ``(host, token)`` after enforcing the exposure policy.

    Read from the environment when not passed explicitly, so tests can exercise the
    policy without starting a server. Raises :class:`UnsafeBindingError` when a
    non-loopback host is configured without a token.
    """
    resolved_host = (host if host is not None else os.environ.get("RAG_HOST", DEFAULT_HOST)).strip()
    resolved_token = (token if token is not None else os.environ.get("RAG_AUTH_TOKEN", "")).strip()
    if not resolved_host:
        raise UnsafeBindingError("RAG_HOST is empty; set it to a loopback address or a host plus RAG_AUTH_TOKEN")
    if resolved_host not in LOOPBACK_HOSTS and not resolved_token:
        raise UnsafeBindingError(
            f"refusing to bind {resolved_host!r} without RAG_AUTH_TOKEN: the MCP endpoint has no caller "
            "identity, so a reachable port means the whole corpus is readable. Set RAG_AUTH_TOKEN (and put "
            f"the service behind a trusted network), or bind {DEFAULT_HOST} instead."
        )
    return resolved_host, resolved_token


def security_settings(host: str, port: int) -> TransportSecuritySettings:
    """Host/Origin validation for the HTTP transports, enabled with the deployment's host."""
    allowed_hosts = [f"{name}:*" for name in ("127.0.0.1", "localhost", "[::1]")]
    allowed_origins = [f"http://{name}:*" for name in ("127.0.0.1", "localhost", "[::1]")]
    if host not in LOOPBACK_HOSTS:
        allowed_hosts.extend([host, f"{host}:{port}"])
        allowed_origins.append(f"http://{host}:{port}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


class BearerTokenGuard:
    """ASGI middleware requiring ``Authorization: Bearer <token>`` on HTTP requests."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(
        self,
        scope: Scope,
        receive: Callable[[], Awaitable[Message]],
        send: Callable[[Message], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        presented = b""
        for name, value in scope.get("headers") or []:
            if name.lower() == b"authorization":
                presented = value
                break
        if not hmac.compare_digest(presented, self._expected):
            await _send_unauthorized(send)
            return
        await self.app(scope, receive, send)


async def _send_unauthorized(send: Callable[[Message], Awaitable[None]]) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", _WWW_AUTHENTICATE),
                (b"content-length", str(len(_UNAUTHORIZED_BODY)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})
