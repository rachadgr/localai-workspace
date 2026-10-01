"""ASGI middleware: request id, rate limiting and security headers."""

from __future__ import annotations

import time
import uuid
from collections import deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from configs.settings import settings


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-process-time-ms"] = str(int((time.perf_counter() - start) * 1000))
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding-window limiter (per client IP)."""

    def __init__(self, app, limit_per_minute: int | None = None) -> None:
        super().__init__(app)
        self.limit = limit_per_minute or settings.rate_limit_per_minute
        self._hits: dict[str, deque[float]] = {}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(("/api/health", "/api/version", "/docs", "/openapi.json")):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        now = time.time()
        bucket = self._hits.setdefault(client, deque())
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded", "class": "RateLimited", "retry_after": 60 - int(now - bucket[0])},
            )
        bucket.append(now)
        return await call_next(request)


__all__ = ["RequestContextMiddleware", "RateLimitMiddleware"]
