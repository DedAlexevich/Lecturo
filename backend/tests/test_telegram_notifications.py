import random
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import (
    AuthIdentity,
    AuthProvider,
    Lecture,
    NotificationEvent,
    NotificationKind,
    NotificationOutcome,
    SourceType,
    User,
)


@pytest.fixture
async def cleanup() -> AsyncIterator[list[uuid.UUID]]:
    user_ids: list[uuid.UUID] = []
    yield user_ids
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()


async def create_user(
    cleanup: list[uuid.UUID],
    telegram: bool = True,
    started_at: datetime | None = None,
    blocked_at: datetime | None = None,
) -> User:
    async with SessionLocal() as session:
        user = User(display_name="Тест", email=f"{uuid.uuid4().hex}@example.org")
        user.identities.append(
            AuthIdentity(provider=AuthProvider.email, provider_user_id=user.email)
        )
        if telegram:
            user.identities.append(
                AuthIdentity(
                    provider=AuthProvider.telegram,
                    provider_user_id=str(random.randint(10**9, 10**10)),
                    bot_started_at=started_at,
                    bot_blocked_at=blocked_at,
                )
            )
        session.add(user)
        await session.commit()
        cleanup.append(user.id)
        return user


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}


async def notifications_state(client, user: User) -> str:
    response = await client.get("/api/v1/me", headers=headers(user))
    assert response.status_code == 200
    for identity in user.identities:
        if identity.provider == AuthProvider.telegram:
            assert identity.provider_user_id not in response.text
    return response.json()["telegram_notifications"]


async def test_without_telegram_not_linked(client, cleanup):
    user = await create_user(cleanup, telegram=False)
    assert await notifications_state(client, user) == "not_linked"


async def test_linked_without_start_requires_start(client, cleanup):
    user = await create_user(cleanup)
    assert await notifications_state(client, user) == "start_required"


async def test_started_bot_is_ready(client, cleanup):
    user = await create_user(cleanup, started_at=datetime.now(UTC))
    assert await notifications_state(client, user) == "ready"


async def test_block_after_start_is_blocked(client, cleanup):
    started = datetime.now(UTC) - timedelta(days=1)
    user = await create_user(cleanup, started_at=started, blocked_at=started + timedelta(hours=1))
    assert await notifications_state(client, user) == "blocked"


async def test_block_without_start_is_blocked(client, cleanup):
    user = await create_user(cleanup, blocked_at=datetime.now(UTC))
    assert await notifications_state(client, user) == "blocked"


async def test_start_after_block_is_ready(client, cleanup):
    blocked = datetime.now(UTC) - timedelta(days=1)
    user = await create_user(cleanup, started_at=blocked + timedelta(hours=1), blocked_at=blocked)
    assert await notifications_state(client, user) == "ready"


async def test_unlink_telegram_resets_state(client, cleanup):
    user = await create_user(cleanup, started_at=datetime.now(UTC))
    response = await client.delete("/api/v1/me/identities/telegram", headers=headers(user))
    assert response.status_code == 200
    assert response.json()["telegram_notifications"] == "not_linked"
    async with SessionLocal() as session:
        session.add(
            AuthIdentity(
                user_id=user.id,
                provider=AuthProvider.telegram,
                provider_user_id=str(random.randint(10**9, 10**10)),
            )
        )
        await session.commit()
    fresh = {"Authorization": f"Bearer {response.headers['X-Access-Token']}"}
    me = await client.get("/api/v1/me", headers=fresh)
    assert me.status_code == 200
    assert me.json()["telegram_notifications"] == "start_required"


async def create_event(user: User) -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title="Лекция", source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        event = NotificationEvent(
            user_id=user.id,
            lecture_id=lecture.id,
            kind=NotificationKind.lecture,
            outcome=NotificationOutcome.ready,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        assert event.attempts == 0
        assert event.next_attempt_at is not None
        assert event.sent_at is None
        assert event.expired_at is None
        return lecture.id, event.id


async def test_lecture_delete_removes_events(cleanup):
    user = await create_user(cleanup)
    lecture_id, event_id = await create_event(user)
    async with SessionLocal() as session:
        await session.execute(delete(Lecture).where(Lecture.id == lecture_id))
        await session.commit()
        assert (
            await session.scalar(
                select(NotificationEvent.id).where(NotificationEvent.id == event_id)
            )
            is None
        )


async def test_user_delete_removes_events(cleanup):
    user = await create_user(cleanup)
    _, event_id = await create_event(user)
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()
        assert (
            await session.scalar(
                select(NotificationEvent.id).where(NotificationEvent.id == event_id)
            )
            is None
        )
