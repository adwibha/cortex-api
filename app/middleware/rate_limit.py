import time
import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.events.bus import get_redis

logger = logging.getLogger(__name__)

# Auth paths require a much tighter limit to deter brute-force / credential stuffing
_AUTH_PATH_PREFIXES = ("/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter using Redis.

    Key: ratelimit:{ip}:{path_bucket}:{window_minute}

    Auth endpoints use a separate tighter limit (auth_rate_limit_per_minute) to
    deter brute-force and credential-stuffing attacks; all other routes use the
    global limit (rate_limit_per_minute).

    Falls back gracefully if Redis is unavailable.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            client_ip = request.client.host if request.client else "unknown"
            window = int(time.time() // 60)

            is_auth_path = request.url.path.startswith(_AUTH_PATH_PREFIXES)
            path_bucket = "auth" if is_auth_path else "global"
            key = f"ratelimit:{client_ip}:{path_bucket}:{window}"

            limit = settings.auth_rate_limit_per_minute if is_auth_path else settings.rate_limit_per_minute

            r = get_redis()
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, 90)
            results = await pipe.execute()
            count = results[0]

            if count > limit:
                retry_after = 60 - int(time.time() % 60)
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": f"Rate limit exceeded. Max {limit} requests/minute.",
                            "details": {"limit": limit, "retry_after": retry_after},
                        },
                        "request_id": getattr(request.state, "request_id", ""),
                    },
                    headers={"Retry-After": str(retry_after)},
                )
        except Exception as exc:
            logger.warning("Rate limit check failed (Redis unavailable?): %s", exc)

        return await call_next(request)
