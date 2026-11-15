"""Loopback guard (target design §8).

Blocks DNS rebinding (Host check), cross-site requests (Origin check on unsafe methods)
and any other local page driving the API (per-launch token on /api/*).
"""

from __future__ import annotations

import hmac

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_HEADER = "x-cs2scout"  # noqa: S105 - a header name, not a secret
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
TOKEN_EXEMPT_PATHS = frozenset({"/api/health"})


class LocalGuard:
    def __init__(self, app: ASGIApp, *, port: int, token: str) -> None:
        if not token:
            raise ValueError("LocalGuard needs a non-empty token")
        self.app = app
        self.token = token
        self.allowed_hosts = frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})
        self.allowed_origins = frozenset(f"http://{host}" for host in self.allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":  # no websockets in this app
            await send({"type": "websocket.close", "code": 1008})
            return

        reason = self._rejection(scope)
        if reason is not None:
            response = JSONResponse({"code": "FORBIDDEN", "message": reason}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _rejection(self, scope: Scope) -> str | None:
        headers = Headers(scope=scope)
        if headers.get("host", "").lower() not in self.allowed_hosts:
            return "Host not allowed"
        if scope["method"] in UNSAFE_METHODS and headers.get("origin") not in self.allowed_origins:
            return "Origin not allowed"
        path = scope["path"]
        if path.startswith("/api/") and path not in TOKEN_EXEMPT_PATHS:
            if not hmac.compare_digest(headers.get(TOKEN_HEADER, ""), self.token):
                return "Missing or invalid session token"
        return None
