"""Uniform boundaries cover both inherited v1 endpoints and new internal endpoints."""

from urllib.parse import urlsplit
from uuid import uuid4

from starlette.responses import JSONResponse

from . import audit
from .db import connection
from .security import authenticate, legacy_allowed
from .settings import settings


class BoundaryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        path, method = scope["path"], scope["method"]
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        protected = path.startswith(("/api/v1/", "/api/internal/"))
        identity = (
            authenticate(headers.get(b"authorization", b"").decode("latin-1"))
            if protected
            else None
        )
        if protected and identity is None:
            return await JSONResponse(
                {"detail": "Bearer credential required"},
                401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
        if identity:
            scope["state"]["principal"] = identity
        if path.startswith("/api/v1/") and not legacy_allowed(path, method, identity):
            return await JSONResponse({"detail": "Role does not permit this operation"}, 403)(
                scope, receive, send
            )
        if method not in {"GET", "HEAD", "OPTIONS"}:
            origin = headers.get(b"origin")
            if origin:
                parsed = urlsplit(origin.decode("latin-1"))
                if (
                    parsed.netloc != headers.get(b"host", b"").decode("latin-1")
                    or parsed.scheme != scope["scheme"]
                ):
                    return await JSONResponse({"detail": "Cross-origin write rejected"}, 403)(
                        scope, receive, send
                    )
            # Buffer only the bounded body; never trust Content-Length alone.
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > settings.max_request_bytes:
                    return await JSONResponse(
                        {"detail": "Request exceeds configured byte limit"}, 413
                    )(scope, receive, send)
                if not message.get("more_body", False):
                    break
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()
        else:
            bounded_receive = receive
        # Legacy mutating handlers do not yet write domain audit events in their transactions.
        # Durable intent is required BEFORE invoking them; new PIA mutations audit atomically.
        if path.startswith("/api/v1/") and method == "POST":
            try:
                async with connection() as conn:
                    await audit.record(
                        conn,
                        identity.subject,
                        "LEGACY_REQUEST_STARTED",
                        path,
                        {"request_id": request_id},
                    )
            except Exception:
                return await JSONResponse({"detail": "Audit/database unavailable"}, 503)(
                    scope, receive, send
                )

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message["headers"] += [
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
                    ),
                ]
                if protected:
                    message["headers"].append((b"cache-control", b"no-store"))
                if path.startswith("/api/v1/") and method == "POST":
                    try:
                        async with connection() as conn:
                            await audit.record(
                                conn,
                                identity.subject,
                                "LEGACY_REQUEST_FINISHED",
                                path,
                                {"request_id": request_id, "status": message["status"]},
                            )
                    except Exception:
                        # Intent was committed. Do not report an unperformed operation on retry.
                        message["headers"].append((b"x-trace-audit", b"completion-record-failed"))
            await send(message)

        await self.app(scope, bounded_receive, secure_send)
