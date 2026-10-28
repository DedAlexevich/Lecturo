import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.models import AuthIdentity, AuthProvider, QuotaCarryover, UsageEntry, UsageSource, User
from app.services import quota
from app.services.account import delete_account
from app.services.auth import register_user
from app.services.telegram_auth import get_or_create_telegram_user
from tests.test_telegram_auth import CONSENTS

USED_SEC = 3600


@pytest.fixture
def policy_in_force(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quota, "today", lambda: quota.CARRYOVER_FROM)


@pytest.fixture
async def created() -> AsyncIterator[list[uuid.UUID]]:
    user_ids: list[uuid.UUID] = []
    yield user_ids
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()


def new_email() -> str:
    return f"Carry-{uuid.uuid4().hex[:8]}@Example.org"


async def spend_and_delete(user_id: uuid.UUID, seconds: int = USED_SEC) -> None:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if seconds:
            session.add(UsageEntry(user_id=user_id, source=UsageSource.weekly, seconds=seconds))
            await session.flush()
        await delete_account(session, user)


async def stored_carryover(provider: AuthProvider, provider_user_id: str) -> QuotaCarryover | None:
    async with SessionLocal() as session:
        return await session.get(QuotaCarryover, quota.identity_hash(provider, provider_user_id))


async def weekly_used(user_id: uuid.UUID) -> int:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        return (await quota.get_quota(session, user)).weekly_used_sec


async def test_email_signup_after_deletion_keeps_weekly_usage(policy_in_force, created):
    email = new_email()
    async with SessionLocal() as session:
        first = await register_user(session, email, "пароль-первый", "Первый")
    async with SessionLocal() as session:
        first_week_start = (await session.get(User, first.id)).quota_week_start
    await spend_and_delete(first.id)

    record = await stored_carryover(AuthProvider.email, email.lower())
    assert record is not None
    assert record.used_sec == USED_SEC
    assert record.week_ends_at == first_week_start + quota.WEEK
    assert email.lower() not in record.identity_hash

    async with SessionLocal() as session:
        second = await register_user(session, email.upper(), "пароль-второй", "Второй")
    created.append(second.id)

    assert await weekly_used(second.id) == USED_SEC
    async with SessionLocal() as session:
        user = await session.get(User, second.id)
        assert user.quota_week_start == first_week_start
    assert await stored_carryover(AuthProvider.email, email.lower()) is None


async def test_telegram_signup_after_deletion_keeps_weekly_usage(policy_in_force, created):
    telegram_id = uuid.uuid4().int % 10**9 + 10**9
    async with SessionLocal() as session:
        first = await get_or_create_telegram_user(
            session, telegram_id, {"first_name": "Иван"}, **CONSENTS
        )
    await spend_and_delete(first.id)

    async with SessionLocal() as session:
        second = await get_or_create_telegram_user(
            session, telegram_id, {"first_name": "Иван"}, **CONSENTS
        )
    created.append(second.id)

    assert second.id != first.id
    assert await weekly_used(second.id) == USED_SEC


async def test_nothing_kept_before_policy_takes_effect(monkeypatch, created):
    monkeypatch.setattr(quota, "today", lambda: quota.CARRYOVER_FROM - timedelta(days=1))
    email = new_email()
    async with SessionLocal() as session:
        first = await register_user(session, email, "пароль-первый", "Первый")
    await spend_and_delete(first.id)

    assert await stored_carryover(AuthProvider.email, email.lower()) is None


async def test_nothing_kept_without_weekly_usage(policy_in_force):
    email = new_email()
    async with SessionLocal() as session:
        first = await register_user(session, email, "пароль-первый", "Первый")
    await spend_and_delete(first.id, seconds=0)

    assert await stored_carryover(AuthProvider.email, email.lower()) is None


async def test_expired_carryover_is_ignored_and_deleted(created):
    email = new_email().lower()
    expired = quota.identity_hash(AuthProvider.email, email)
    async with SessionLocal() as session:
        session.add(
            QuotaCarryover(
                identity_hash=expired,
                used_sec=USED_SEC,
                week_ends_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await session.commit()

    async with SessionLocal() as session:
        user = await register_user(session, email, "пароль-новый", "Новый")
    created.append(user.id)
    assert await weekly_used(user.id) == 0

    assert await quota.delete_expired_carryovers({}) >= 1
    async with SessionLocal() as session:
        assert (
            await session.scalar(
                select(QuotaCarryover).where(QuotaCarryover.identity_hash == expired)
            )
        ) is None


async def test_every_sign_in_method_keeps_weekly_usage(policy_in_force, created):
    email = new_email().lower()
    telegram_id = uuid.uuid4().int % 10**9 + 10**9
    async with SessionLocal() as session:
        first = await register_user(session, email, "пароль-первый", "Первый")
        session.add(
            AuthIdentity(
                user_id=first.id, provider=AuthProvider.telegram, provider_user_id=str(telegram_id)
            )
        )
        await session.commit()
    await spend_and_delete(first.id)

    assert await stored_carryover(AuthProvider.email, email) is not None
    async with SessionLocal() as session:
        second = await get_or_create_telegram_user(
            session, telegram_id, {"first_name": "Иван"}, **CONSENTS
        )
    created.append(second.id)
    assert await weekly_used(second.id) == USED_SEC
    async with SessionLocal() as session:
        await session.execute(
            delete(QuotaCarryover).where(
                QuotaCarryover.identity_hash == quota.identity_hash(AuthProvider.email, email)
            )
        )
        await session.commit()
