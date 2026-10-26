from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError


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
