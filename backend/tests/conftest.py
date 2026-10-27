from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.main import app
from app.models import (
    NotificationEvent,
    NotificationKind,
    NotificationOutcome,
    Payment,
    User,
)
from app.services.legal import read_document


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def user() -> AsyncIterator[User]:
    async with SessionLocal() as session:
        user = User(
            display_name="Тест",
            ai_transfer_accepted_at=datetime.now(UTC),
            ai_transfer_revision=read_document("ai-transfer").revision_date,
        )
        session.add(user)
        await session.commit()
        yield user
        payment_ids = (
            await session.scalars(select(Payment.id).where(Payment.user_id == user.id))
        ).all()
        await session.delete(user)
        await session.execute(delete(Payment).where(Payment.id.in_(payment_ids)))
        await session.commit()


@pytest.fixture
async def reset_auth_rate_limits() -> AsyncIterator[None]:
    keys = ("rate:login:ip:127.0.0.1", "rate:register:127.0.0.1")
    redis = Redis.from_url(get_settings().redis_url)
    await redis.delete(*keys)
    yield
    await redis.delete(*keys)
    await redis.aclose()


@pytest.fixture
def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture(autouse=True)
def retry_pauses(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    pauses: list[float] = []

    async def record(seconds: float) -> None:
        pauses.append(seconds)

    monkeypatch.setattr("app.providers.retry.sleep", record)
    return pauses


async def notifications(lecture_id) -> list[tuple[NotificationKind, NotificationOutcome]]:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(NotificationEvent.kind, NotificationEvent.outcome)
            .where(NotificationEvent.lecture_id == lecture_id)
            .order_by(NotificationEvent.created_at)
        )
        return [(kind, outcome) for kind, outcome in rows]
