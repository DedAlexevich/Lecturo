import hashlib

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings


async def is_rate_limited(redis_url: str, key: str, limit: int, window_seconds: int) -> bool:
    redis = Redis.from_url(redis_url)
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            count, _ = await pipe.execute()
    finally:
        await redis.aclose()
    return count > limit


async def enforce_rate_limit(redis_url: str, key: str, limit: int, window_seconds: int) -> None:
    try:
        limited = await is_rate_limited(redis_url, key, limit, window_seconds)
    except (OSError, RedisError) as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Сервис временно недоступен, попробуйте позже"
        ) from error
    if limited:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много запросов")


async def enforce_mail_rate_limit(request: Request, subject: str) -> None:
    settings = get_settings()
    digest = hashlib.sha256(subject.encode()).hexdigest()
    ip = request.client.host if request.client else "unknown"
    checks = [
        (f"rate:auth-mail:subject:{digest}", settings.auth_mail_rate_limit),
        (f"rate:auth-mail:ip:{ip}", settings.auth_mail_ip_rate_limit),
    ]
    try:
        for key, limit in checks:
            if await is_rate_limited(
                settings.redis_url, key, limit, settings.auth_mail_rate_window_seconds
            ):
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Слишком много запросов писем, попробуйте позже",
                )
    except (OSError, RedisError) as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Сервис временно недоступен, попробуйте позже"
        ) from error
