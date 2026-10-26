from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import HourPackage, Lecture, SourceType, Subscription, UsageEntry, User
from app.services import quota

SETTINGS = Settings(
    free_weekly_seconds=3600,
    subscription_weekly_seconds=5 * 3600,
    hour_packages={10: 349, 5: 199},
)
WEEK_START = datetime(2026, 10, 5, 12, tzinfo=UTC)
NOW = WEEK_START + timedelta(days=2)


async def prepare(user, packages=(), subscription=None) -> list:
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        db_user.quota_week_start = WEEK_START
        created = []
        for index, seconds in enumerate(packages):
            package = HourPackage(
                user_id=user.id,
                seconds_total=seconds,
                seconds_left=seconds,
                created_at=WEEK_START - timedelta(days=10 - index),
            )
            session.add(package)
            created.append(package)
        if subscription:
            starts_at, ends_at = subscription
            session.add(Subscription(user_id=user.id, starts_at=starts_at, ends_at=ends_at))
        await session.commit()
        return [package.id for package in created]


async def new_lecture(user) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title="Лекция", source_type=SourceType.upload)
        session.add(lecture)
        await session.commit()
        return lecture


async def charge(user, lecture, seconds, now=NOW) -> bool:
    async with SessionLocal() as session:
        charged = await quota.charge_lecture(
            session, user.id, lecture.id, seconds, now=now, settings=SETTINGS
        )
        await session.commit()
        return charged


async def refund(lecture) -> int:
    async with SessionLocal() as session:
        refunded = await quota.refund_lecture(session, lecture.id)
        await session.commit()
        return refunded


async def read_quota(user, now=NOW) -> quota.Quota:
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        result = await quota.get_quota(session, db_user, now=now, settings=SETTINGS)
        await session.commit()
        return result


async def packages_left(package_ids) -> list[int]:
    async with SessionLocal() as session:
        return [(await session.get(HourPackage, pid)).seconds_left for pid in package_ids]


def test_week_start_moves_by_whole_weeks():
    assert quota.current_week_start(WEEK_START, WEEK_START) == WEEK_START
    almost = WEEK_START + timedelta(days=7) - timedelta(microseconds=1)
    assert quota.current_week_start(WEEK_START, almost) == WEEK_START
    exact = WEEK_START + timedelta(days=7)
    assert quota.current_week_start(WEEK_START, exact) == exact
    later = WEEK_START + timedelta(days=17, hours=5)
    assert quota.current_week_start(WEEK_START, later) == WEEK_START + timedelta(days=14)


async def test_fresh_user_has_free_weekly_limit(user):
    await prepare(user)

    result = await read_quota(user)

    assert result.weekly_limit_sec == 3600
    assert result.weekly_used_sec == 0
    assert result.package_left_sec == 0
    assert result.resets_at == WEEK_START + timedelta(days=7)
    assert result.subscription_until is None


async def test_charge_uses_week_then_oldest_package(user):
    package_ids = await prepare(user, packages=[1000, 5000])
    lecture = await new_lecture(user)

    assert await charge(user, lecture, 3600 + 1500)

    result = await read_quota(user)
    assert result.weekly_used_sec == 3600
    assert result.package_left_sec == 4500
    assert await packages_left(package_ids) == [0, 4500]


async def test_fractional_duration_rounds_up(user):
    await prepare(user)
    lecture = await new_lecture(user)

    assert await charge(user, lecture, 99.2)

    assert (await read_quota(user)).weekly_used_sec == 100


async def test_charge_exactly_available(user):
    await prepare(user, packages=[600])
    lecture = await new_lecture(user)

    assert await charge(user, lecture, 3600 + 600)

    assert (await read_quota(user)).available_sec == 0


async def test_not_enough_quota_charges_nothing(user):
    package_ids = await prepare(user, packages=[600])
    lecture = await new_lecture(user)

    assert not await charge(user, lecture, 3600 + 601)

    result = await read_quota(user)
    assert result.weekly_used_sec == 0
    assert await packages_left(package_ids) == [600]


async def test_repeated_charge_is_not_counted_twice(user):
    package_ids = await prepare(user, packages=[3600])
    lecture = await new_lecture(user)

    assert await charge(user, lecture, 4000)
    assert await charge(user, lecture, 4000)

    result = await read_quota(user)
    assert result.weekly_used_sec == 3600
    assert await packages_left(package_ids) == [3200]


async def test_refund_returns_week_and_packages(user):
    package_ids = await prepare(user, packages=[3600])
    lecture = await new_lecture(user)
    await charge(user, lecture, 4000)

    assert await refund(lecture) == 4000

    result = await read_quota(user)
    assert result.weekly_used_sec == 0
    assert await packages_left(package_ids) == [3600]
    assert await refund(lecture) == 0
    assert await charge(user, lecture, 4000)
    assert (await read_quota(user)).weekly_used_sec == 3600


async def test_new_week_resets_usage_and_keeps_packages(user):
    package_ids = await prepare(user, packages=[1800])
    lecture = await new_lecture(user)
    await charge(user, lecture, 4000)

    later = WEEK_START + timedelta(days=15)
    result = await read_quota(user, now=later)

    assert result.weekly_used_sec == 0
    assert result.package_left_sec == 1400
    assert result.resets_at == WEEK_START + timedelta(days=21)
    assert await packages_left(package_ids) == [1400]
    async with SessionLocal() as session:
        stored = await session.get(User, user.id)
        assert stored.quota_week_start == WEEK_START + timedelta(days=14)


async def test_usage_before_reset_does_not_count(user):
    await prepare(user)
    old = await new_lecture(user)
    await charge(user, old, 3000, now=WEEK_START + timedelta(days=6, hours=23))
    fresh = await new_lecture(user)

    assert await charge(user, fresh, 3600, now=WEEK_START + timedelta(days=7))

    result = await read_quota(user, now=WEEK_START + timedelta(days=7))
    assert result.weekly_used_sec == 3600


async def test_active_subscription_raises_limit(user):
    until = NOW + timedelta(days=20)
    await prepare(user, subscription=(NOW - timedelta(days=10), until))

    result = await read_quota(user)

    assert result.weekly_limit_sec == 5 * 3600
    assert result.subscription_until == until


async def test_expired_subscription_gives_free_limit(user):
    await prepare(user, subscription=(NOW - timedelta(days=30), NOW))
    lecture = await new_lecture(user)

    assert not await charge(user, lecture, 3601)

    result = await read_quota(user)
    assert result.weekly_limit_sec == 3600
    assert result.subscription_until is None


async def test_refund_only_touches_own_lecture(user):
    await prepare(user)
    first = await new_lecture(user)
    second = await new_lecture(user)
    await charge(user, first, 1000)
    await charge(user, second, 500)

    await refund(first)

    async with SessionLocal() as session:
        left = (await session.scalars(select(UsageEntry.lecture_id))).all()
    assert first.id not in left
    assert second.id in left
    assert (await read_quota(user)).weekly_used_sec == 500


def test_products_come_from_settings():
    products = quota.list_products(SETTINGS)

    assert [p.code for p in products] == ["subscription", "hours_5", "hours_10"]
    assert products[0].price_rub == SETTINGS.subscription_price_rub
    assert products[0].seconds is None
    assert products[1].price_rub == 199
    assert products[1].seconds == 5 * 3600
    assert products[2].seconds == 10 * 3600


async def test_quota_endpoint(client, user, auth_headers):
    response = await client.get("/api/v1/billing/quota", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["weekly_used_sec"] == 0
    assert body["package_left_sec"] == 0
    assert body["subscription_until"] is None
    assert "resets_at" in body


async def test_quota_endpoint_requires_auth(client):
    response = await client.get("/api/v1/billing/quota")

    assert response.status_code == 401


async def test_products_endpoint(client):
    response = await client.get("/api/v1/billing/products")

    assert response.status_code == 200
    assert response.json()[0]["code"] == "subscription"
