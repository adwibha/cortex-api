"""
Redis pub/sub event bus.

Producers call `publish(EventType.X, payload)`.
Consumers register with `@subscribe(EventType.X)` and are started in the app lifespan.
"""
import asyncio
import json
import logging
from enum import Enum
from typing import Awaitable, Callable, Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None
_handlers: dict[str, list[Callable]] = {}


class EventType(str, Enum):
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_COMPLETED = "task.completed"
    TASK_DELETED = "task.deleted"
    JOB_FINISHED = "job.finished"
    AI_SUMMARY_GENERATED = "ai.summary_generated"


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def publish(event: EventType, payload: dict) -> None:
    try:
        r = get_redis()
        message = json.dumps({"event": event.value, "payload": payload})
        await r.publish(f"events:{event.value}", message)
    except Exception as exc:
        logger.warning("Event publish failed (%s): %s", event, exc)


def subscribe(event_type: EventType):
    """Decorator to register a handler for an event type."""
    def decorator(fn: Callable[[dict], Awaitable[None]]):
        _handlers.setdefault(event_type.value, []).append(fn)
        return fn
    return decorator


async def start_subscribers() -> None:
    """Start all registered subscribers as background tasks."""
    if not _handlers:
        return

    r = get_redis()
    channels = [f"events:{ev}" for ev in _handlers]
    pubsub = r.pubsub()
    await pubsub.subscribe(*channels)
    asyncio.create_task(_dispatch_loop(pubsub), name="event-bus-dispatcher")
    logger.info("Event bus started, listening on: %s", channels)


async def _dispatch_loop(pubsub) -> None:
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
                event_key = data.get("event", "")
                payload = data.get("payload", {})
                for handler in _handlers.get(event_key, []):
                    try:
                        await handler(payload)
                    except Exception as exc:
                        logger.error("Event handler error (%s): %s", event_key, exc)
            except Exception as exc:
                logger.error("Event dispatch error: %s", exc)
    except asyncio.CancelledError:
        await pubsub.unsubscribe()


async def close() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
