from app.core.config import get_settings
from app.core.redis import close_redis, get_redis


async def test_redis_client_is_shared_and_closed():
    url = get_settings().redis_url
    client = get_redis(url)

    assert get_redis(url) is client
    assert await client.ping()

    await close_redis()

    assert get_redis(url) is not client
