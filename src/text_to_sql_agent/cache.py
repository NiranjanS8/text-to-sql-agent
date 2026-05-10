import hashlib
import json
import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from text_to_sql_agent.config import Settings, get_settings


LOGGER = logging.getLogger(__name__)
CACHE_KEY_VERSION = "v1"


def build_cache_key(namespace: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"text-to-sql:{CACHE_KEY_VERSION}:{namespace}:{digest}"


def get_cached_text(
    namespace: str,
    payload: dict[str, Any],
    factory: Callable[[], str],
    *,
    ttl_seconds: int | None = None,
    settings: Settings | None = None,
) -> str:
    active_settings = settings or get_settings()
    client = get_redis_client(active_settings.redis_url)
    if client is None:
        return factory()

    key = build_cache_key(namespace, payload)
    try:
        cached = client.get(key)
    except Exception as exc:
        LOGGER.warning("Redis cache read failed for %s: %s", namespace, exc)
        return factory()

    if cached is not None:
        return _decode_cached_text(cached)

    value = factory()
    try:
        client.setex(key, ttl_seconds or active_settings.cache_ttl_seconds, value)
    except Exception as exc:
        LOGGER.warning("Redis cache write failed for %s: %s", namespace, exc)
    return value


def redis_health(settings: Settings | None = None) -> dict[str, str]:
    active_settings = settings or get_settings()
    if not active_settings.redis_url:
        return {"status": "disabled", "message": "REDIS_URL is not configured."}

    client = get_redis_client(active_settings.redis_url)
    if client is None:
        return {"status": "unavailable", "message": "Redis client is not available."}

    try:
        client.ping()
    except Exception as exc:
        return {"status": "unavailable", "message": str(exc)}
    return {"status": "ok", "message": "Redis cache is reachable."}


@lru_cache
def get_redis_client(redis_url: str | None) -> Any | None:
    if not redis_url:
        return None

    try:
        from redis import Redis
    except ImportError:
        LOGGER.warning("redis package is not installed; cache is disabled.")
        return None

    return Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)


def _decode_cached_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)
