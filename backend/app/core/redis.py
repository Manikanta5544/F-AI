from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

# ── Two Redis instances — intentionally separate ───────────────────────────────
# Queue Redis: Celery broker — appendonly persistence, no eviction policy
# Cache Redis: LRU eviction (allkeys-lru), volatile data only
_queue_client: aioredis.Redis | None = None
_cache_client: aioredis.Redis | None = None


async def get_queue_redis() -> aioredis.Redis:
    global _queue_client
    if _queue_client is None:
        _queue_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_keepalive=True,
        )
    return _queue_client


async def get_cache_redis() -> aioredis.Redis:
    global _cache_client
    if _cache_client is None:
        _cache_client = aioredis.from_url(
            settings.REDIS_CACHE_URL,
            decode_responses=True,
            socket_keepalive=True,
        )
    return _cache_client


async def close_redis() -> None:
    """Called on application shutdown."""
    global _queue_client, _cache_client
    if _queue_client:
        await _queue_client.aclose()
        _queue_client = None
    if _cache_client:
        await _cache_client.aclose()
        _cache_client = None


# ── Cache helpers ─────────────────────────────────────────────────────────────
async def cache_get(key: str) -> Any | None:
    client = await get_cache_redis()
    raw = await client.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


async def cache_set(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    client = await get_cache_redis()
    await client.setex(key, ttl_seconds, json.dumps(value, default=str))


async def cache_delete(key: str) -> None:
    client = await get_cache_redis()
    await client.delete(key)


# ── SSE event publisher via Redis Streams ─────────────────────────────────────
async def publish_job_event(
    job_id: str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """
    Publish a job status event into a Redis Stream.
    The SSE endpoint reads from this stream and forwards to the browser.
    Stream key: job:{job_id}:events  (maxlen 100 — capped ring buffer)
    """
    client = await get_queue_redis()
    await client.xadd(
        f"job:{job_id}:events",
        {"event": event_type, "data": json.dumps(data, default=str)},
        maxlen=100,
    )