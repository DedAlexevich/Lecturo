from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import Subscription, User
from app.services import quota

SETTINGS = Settings(free_video_retention_days=3, subscription_video_retention_days=30)
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


async def add_subscription(user, starts_at, ends_at) -> None:
    async with SessionLocal() as session:
        session.add(Subscription(user_id=user.id, starts_at=starts_at, ends_at=ends_at))
        await session.commit()


async def check(user, now=NOW) -> tuple[bool, int]:
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        active = await quota.has_subscription(session, db_user, now=now)
        days = await quota.video_retention_days(session, db_user, now=now, settings=SETTINGS)
        return active, days


async def test_user_without_subscription(user):
    assert await check(user) == (False, 3)


async def test_user_with_active_subscription(user):
    await add_subscription(user, NOW - timedelta(days=1), NOW + timedelta(days=29))

    assert await check(user) == (True, 30)


async def test_expired_subscription_is_free(user):
    await add_subscription(user, NOW - timedelta(days=31), NOW - timedelta(days=1))

    assert await check(user) == (False, 3)


async def test_future_subscription_is_not_active_yet(user):
    await add_subscription(user, NOW + timedelta(days=1), NOW + timedelta(days=31))

    assert await check(user) == (False, 3)
    assert await check(user, now=NOW + timedelta(days=2)) == (True, 30)
