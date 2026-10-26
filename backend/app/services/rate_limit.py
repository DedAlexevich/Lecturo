from redis.asyncio import Redis


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
