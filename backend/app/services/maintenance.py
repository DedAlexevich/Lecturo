import json
import logging
import time
from datetime import UTC, datetime

from arq import Retry
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

MAINTENANCE_KEY = "lecturo:maintenance"
CACHE_SECONDS = 2.0
JOB_DEFER_SECONDS = 60
MAINTENANCE_MESSAGE = "Идут технические работы, сайт скоро вернётся"

cache: dict[str, float | bool] = {"checked_at": 0.0, "active": False}


async def is_active(use_cache: bool = True) -> bool:
    now = time.monotonic()
    if use_cache and now - float(cache["checked_at"]) < CACHE_SECONDS:
        return bool(cache["active"])
    redis = get_redis(get_settings().redis_url)
    try:
        active = bool(await redis.exists(MAINTENANCE_KEY))
    except (OSError, RedisError):
        logger.warning("Не удалось прочитать флаг режима обслуживания")
        return False
    cache["checked_at"] = now
    cache["active"] = active
    return active


async def enable(reason: str) -> None:
    redis = get_redis(get_settings().redis_url)
    payload = {"reason": reason, "since": datetime.now(UTC).isoformat()}
    await redis.set(MAINTENANCE_KEY, json.dumps(payload))
    cache["checked_at"] = 0.0


async def disable() -> None:
    redis = get_redis(get_settings().redis_url)
    await redis.delete(MAINTENANCE_KEY)
    cache["checked_at"] = 0.0


async def details() -> dict | None:
    redis = get_redis(get_settings().redis_url)
    raw = await redis.get(MAINTENANCE_KEY)
    return json.loads(raw) if raw else None


async def hold_job_while_active() -> None:
    if await is_active():
        raise Retry(defer=JOB_DEFER_SECONDS)
