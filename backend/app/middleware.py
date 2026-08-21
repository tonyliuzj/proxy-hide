from __future__ import annotations

import hmac
import uuid
from typing import ClassVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config import get_settings
from app.errors import error_response


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id", "")
        try:
            request_id = str(uuid.UUID(request_id)) if request_id else str(uuid.uuid4())
        except ValueError:
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    _SAFE_METHODS: ClassVar[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS"})
    _TOKEN_EXEMPT_PATHS: ClassVar[frozenset[str]] = frozenset(
        {"/api/v1/auth/login", "/api/v1/auth/setup"}
    )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in self._SAFE_METHODS:
            return await call_next(request)
        if not request.url.path.startswith("/api/v1/"):
            return await call_next(request)
        settings = get_settings()
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in settings.allowed_origins:
            return error_response(
                request, 403, "ORIGIN_REJECTED", "The request origin is not allowed."
            )
        if request.url.path in self._TOKEN_EXEMPT_PATHS:
            return await call_next(request)
        token = request.cookies.get(settings.session_cookie_name)
        header_token = request.headers.get("x-csrf-token")
        cookie_token = request.cookies.get(settings.csrf_cookie_name)
        if not token or not header_token or not cookie_token:
            return error_response(request, 403, "CSRF_FAILED", "CSRF validation failed.")
        session = await request.app.state.session_store.get(token)
        if (
            session is None
            or not hmac.compare_digest(header_token, cookie_token)
            or not hmac.compare_digest(header_token, session.csrf_token)
        ):
            return error_response(request, 403, "CSRF_FAILED", "CSRF validation failed.")
        return await call_next(request)
