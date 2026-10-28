import asyncio

from fastapi import APIRouter, Response, status
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engine

CHECK_TIMEOUT_SECONDS = 3

router = APIRouter(tags=["health"])


async def database_ready() -> bool:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS), engine.connect() as connection:
            await connection.execute(text("select 1"))
    except Exception:
        return False
    return True


async def redis_ready() -> bool:
    redis = Redis.from_url(
        get_settings().redis_url,
        socket_connect_timeout=CHECK_TIMEOUT_SECONDS,
        socket_timeout=CHECK_TIMEOUT_SECONDS,
    )
    try:
        await redis.ping()
    except Exception:
        return False
    finally:
        await redis.aclose()
    return True


@router.head("/health", include_in_schema=False)
@router.get("/health")
async def health(response: Response) -> dict[str, str]:
    database, redis = await asyncio.gather(database_ready(), redis_ready())
    if database and redis:
        return {"status": "ok"}
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "unavailable",
        "database": "ok" if database else "error",
        "redis": "ok" if redis else "error",
    }
