import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.db import SessionLocal
from app.core.deps import RequireSubscription
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


@pytest.fixture
async def guarded_client() -> AsyncIterator[AsyncClient]:
    guarded_app = FastAPI()

    @guarded_app.get("/guarded")
    async def guarded(user: RequireSubscription) -> dict[str, str]:
        return {"user_id": str(user.id)}

    transport = ASGITransport(app=guarded_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_require_subscription_rejects_free_user(guarded_client, user, auth_headers):
    response = await guarded_client.get("/guarded", headers=auth_headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "subscription_required"


async def test_require_subscription_allows_subscriber(guarded_client, user, auth_headers):
    now = datetime.now(UTC)
    await add_subscription(user, now - timedelta(days=1), now + timedelta(days=29))

    response = await guarded_client.get("/guarded", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"user_id": str(user.id)}


async def test_require_subscription_needs_login(guarded_client):
    response = await guarded_client.get("/guarded")

    assert response.status_code == 401


PAID_ENDPOINTS = [
    ("post", "/api/v1/lectures/{id}/quiz"),
    ("get", "/api/v1/lectures/{id}/quiz"),
    ("post", "/api/v1/courses/{id}/exam-sheet"),
    ("get", "/api/v1/courses/{id}/exam-sheet"),
]


@pytest.mark.parametrize(("method", "path"), PAID_ENDPOINTS)
async def test_paid_endpoints_reject_free_user(client, user, auth_headers, method, path):
    response = await client.request(method, path.format(id=uuid.uuid4()), headers=auth_headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "subscription_required"


@pytest.mark.parametrize(("method", "path"), PAID_ENDPOINTS)
async def test_paid_endpoints_pass_subscriber(client, user, auth_headers, method, path):
    now = datetime.now(UTC)
    await add_subscription(user, now - timedelta(days=1), now + timedelta(days=29))

    response = await client.request(method, path.format(id=uuid.uuid4()), headers=auth_headers)

    assert response.status_code == 501


@pytest.mark.parametrize(("method", "path"), PAID_ENDPOINTS)
async def test_paid_endpoints_need_login(client, method, path):
    response = await client.request(method, path.format(id=uuid.uuid4()))

    assert response.status_code == 401
