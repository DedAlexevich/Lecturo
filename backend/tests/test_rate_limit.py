import uuid

from app.core.config import get_settings
from app.services.rate_limit import is_rate_limited


async def test_limit_is_exceeded_after_threshold():
    key = f"rate:test:{uuid.uuid4()}"
    url = get_settings().redis_url

    results = [await is_rate_limited(url, key, 2, 60) for _ in range(3)]

    assert results == [False, False, True]
