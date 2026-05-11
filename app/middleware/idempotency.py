"""
Idempotency key middleware.

For POST requests with an `Idempotency-Key` header:
- First call: process normally, cache response body + status in Redis (TTL 24h)
- Repeated call: return cached response immediately, no downstream processing

Applies to all POST endpoints.
"""
import json
import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.events.bus import get_redis

logger = logging.getLogger(__name__)

_TTL = 86_400  # 24 hours


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method != "POST":
            return await call_next(request)

        key_header = request.headers.get("Idempotency-Key")
        if not key_header:
            return await call_next(request)

        redis_key = f"idempotency:{request.url.path}:{key_header}"

        try:
            r = get_redis()
            cached = await r.get(redis_key)
            if cached:
                data = json.loads(cached)
                logger.debug("Idempotency cache hit for key: %s", key_header)
                return JSONResponse(
                    status_code=data["status_code"],
                    content=data["body"],
                    headers={"X-Idempotency-Replayed": "true"},
                )
        except Exception as exc:
            logger.warning("Idempotency cache read failed: %s", exc)

        response = await call_next(request)

        try:
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk

            body_str = body_bytes.decode("utf-8")

            try:
                body_json = json.loads(body_str)
            except Exception:
                body_json = body_str

            cache_data = json.dumps({"status_code": response.status_code, "body": body_json})
            r = get_redis()
            await r.set(redis_key, cache_data, ex=_TTL)

            return Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception as exc:
            logger.warning("Idempotency cache write failed: %s", exc)
            return response
