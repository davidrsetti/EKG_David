"""
api/middleware.py — Rate limiting and request audit injection.
"""
from __future__ import annotations
import time
from collections import defaultdict, deque

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from nexus.config.settings import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter per user_id extracted from JWT sub claim.
    Falls back to IP address if no token is present.
    """

    def __init__(self, app, requests_per_hour: int | None = None):
        super().__init__(app)
        self._limit  = requests_per_hour or settings.security.rate_limit_per_hour
        self._window = 3600  # seconds
        self._buckets: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip health checks
        if request.url.path in ("/health", "/v1/health/graph"):
            return await call_next(request)

        key = self._identify(request)
        now = time.time()
        bucket = self._buckets[key]

        # Evict old entries
        while bucket and bucket[0] < now - self._window:
            bucket.popleft()

        if len(bucket) >= self._limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "detail": f"Maximum {self._limit} requests per hour exceeded.",
                    "retry_after": int(self._window - (now - bucket[0])),
                },
            )

        bucket.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"]     = str(self._limit)
        response.headers["X-RateLimit-Remaining"] = str(self._limit - len(bucket))
        return response

    @staticmethod
    def _identify(request: Request) -> str:
        """Extract user identity from JWT or fall back to client IP."""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            try:
                import jwt as _jwt
                from nexus.config.settings import settings as _s
                payload = _jwt.decode(
                    auth[7:], _s.security.jwt_secret,
                    algorithms=[_s.security.jwt_algorithm],
                    options={"verify_exp": False},
                )
                return payload.get("sub", "anonymous")
            except Exception:
                pass
        return request.client.host if request.client else "unknown"
