import hashlib
import logging

from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)


async def is_rate_limited(redis_url: str, key: str, limit: int, window_seconds: int) -> bool:
    async with get_redis(redis_url).pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        count, _ = await pipe.execute()
    return count > limit


async def reset_rate_limit(redis_url: str, key: str) -> None:
    try:
        await get_redis(redis_url).delete(key)
    except (OSError, RedisError):
        logger.warning("Не удалось сбросить лимит %s", key, exc_info=True)


async def enforce_rate_limit(
    redis_url: str,
    key: str,
    limit: int,
    window_seconds: int,
    message: str = "Слишком много запросов",
) -> None:
    try:
        limited = await is_rate_limited(redis_url, key, limit, window_seconds)
    except (OSError, RedisError) as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Сервис временно недоступен, попробуйте позже"
        ) from error
    if limited:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)


async def ensure_below_limit(redis_url: str, key: str, limit: int) -> None:
    try:
        count = int(await get_redis(redis_url).get(key) or 0)
    except (OSError, RedisError) as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Сервис временно недоступен, попробуйте позже"
        ) from error
    if count >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много запросов")


async def count_failure(redis_url: str, key: str, window_seconds: int) -> None:
    try:
        async with get_redis(redis_url).pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            await pipe.execute()
    except (OSError, RedisError):
        logger.warning("Не удалось учесть неудачную попытку %s", key, exc_info=True)


CHECK_AND_INCREMENT = """
for i = 1, #KEYS do
    local current = tonumber(redis.call('GET', KEYS[i]) or '0')
    if current >= tonumber(ARGV[i]) then
        return 1
    end
end
for i = 1, #KEYS do
    redis.call('INCR', KEYS[i])
    redis.call('EXPIRE', KEYS[i], tonumber(ARGV[#ARGV]), 'NX')
end
return 0
"""


async def is_any_limited(
    redis_url: str, checks: list[tuple[str, int]], window_seconds: int
) -> bool:
    result = await get_redis(redis_url).eval(
        CHECK_AND_INCREMENT,
        len(checks),
        *[key for key, _ in checks],
        *[limit for _, limit in checks],
        window_seconds,
    )
    return bool(result)


async def enforce_mail_rate_limit(request: Request, subject: str, per_ip: bool = False) -> None:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    scoped = f"{subject}|{ip}" if per_ip else subject
    digest = hashlib.sha256(scoped.encode()).hexdigest()
    checks = [
        (f"rate:auth-mail:subject:{digest}", settings.auth_mail_rate_limit),
        (f"rate:auth-mail:ip:{ip}", settings.auth_mail_ip_rate_limit),
    ]
    if per_ip:
        address_digest = hashlib.sha256(subject.encode()).hexdigest()
        checks.append(
            (f"rate:auth-mail:address:{address_digest}", settings.auth_mail_address_rate_limit)
        )
    try:
        limited = await is_any_limited(
            settings.redis_url, checks, settings.auth_mail_rate_window_seconds
        )
    except (OSError, RedisError) as error:
        logger.exception("Хранилище лимитов недоступно")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Сервис временно недоступен, попробуйте позже"
        ) from error
    if limited:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много запросов писем, попробуйте позже"
        )


async def charge_budget(
    redis_url: str, key: str, amount: int, limit: int, window_seconds: int
) -> bool:
    redis = get_redis(redis_url)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incrby(key, amount)
        pipe.expire(key, window_seconds, nx=True)
        total, _ = await pipe.execute()
    if total > limit:
        await redis.decrby(key, amount)
        return False
    return True


async def refund_budget(redis_url: str, key: str, amount: int) -> None:
    try:
        await get_redis(redis_url).decrby(key, amount)
    except (OSError, RedisError):
        logger.warning("Не удалось вернуть лимит %s", key, exc_info=True)
