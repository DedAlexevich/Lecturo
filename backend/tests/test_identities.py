import hashlib
import hmac
import json
import random
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

import pytest
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import (
    AuthIdentity,
    AuthProvider,
    Course,
    Lecture,
    SourceType,
    Subscription,
    User,
)
from app.services.auth import hash_password

BOT_TOKEN = "123456:test-bot-token"
PASSWORD = "correct-horse"


@pytest.fixture(autouse=True)
def bot_token(monkeypatch) -> str:
    monkeypatch.setattr(get_settings(), "telegram_bot_token", BOT_TOKEN)
    return BOT_TOKEN


@pytest.fixture
def telegram_id() -> int:
    return random.randint(10**9, 10**10)


@pytest.fixture
async def cleanup() -> AsyncIterator[list[uuid.UUID]]:
    user_ids: list[uuid.UUID] = []
    yield user_ids
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()


async def create_user(cleanup: list[uuid.UUID], **fields) -> User:
    providers = fields.pop("providers", [])
    async with SessionLocal() as session:
        user = User(display_name="Тест", **fields)
        for provider, value in providers:
            user.identities.append(AuthIdentity(provider=provider, provider_user_id=value))
        session.add(user)
        await session.commit()
        cleanup.append(user.id)
        return user


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}


def signed(telegram_id: int) -> dict:
    fields = {"id": telegram_id, "first_name": "Иван", "auth_date": int(time.time())}
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return fields


def email_address() -> str:
    return f"{uuid.uuid4().hex}@example.org"


async def test_link_telegram_adds_identity(client, cleanup, telegram_id):
    user = await create_user(cleanup, email=email_address())
    response = await client.post(
        "/api/v1/me/identities/telegram", json=signed(telegram_id), headers=headers(user)
    )
    assert response.status_code == 200
    assert [item["provider"] for item in response.json()["identities"]] == ["telegram"]
    async with SessionLocal() as session:
        stored = await session.get(User, user.id)
        assert stored.telegram_chat_id == telegram_id


async def test_link_telegram_is_idempotent(client, cleanup, telegram_id):
    user = await create_user(cleanup)
    for _ in range(2):
        response = await client.post(
            "/api/v1/me/identities/telegram", json=signed(telegram_id), headers=headers(user)
        )
        assert response.status_code == 200
    assert len(response.json()["identities"]) == 1


async def test_link_telegram_of_other_account_conflicts(client, cleanup, telegram_id):
    owner = await create_user(
        cleanup,
        email=email_address(),
        providers=[(AuthProvider.telegram, str(telegram_id))],
        telegram_chat_id=telegram_id,
    )
    user = await create_user(cleanup)
    response = await client.post(
        "/api/v1/me/identities/telegram", json=signed(telegram_id), headers=headers(user)
    )
    assert response.status_code == 409
    async with SessionLocal() as session:
        identity = await session.scalar(
            select(AuthIdentity).where(AuthIdentity.provider_user_id == str(telegram_id))
        )
        assert identity.user_id == owner.id


async def test_link_telegram_with_second_telegram_conflicts(client, cleanup, telegram_id):
    user = await create_user(cleanup, providers=[(AuthProvider.telegram, str(telegram_id))])
    response = await client.post(
        "/api/v1/me/identities/telegram", json=signed(telegram_id + 1), headers=headers(user)
    )
    assert response.status_code == 409


async def test_link_telegram_rejects_forged_hash(client, cleanup, telegram_id):
    user = await create_user(cleanup)
    payload = signed(telegram_id) | {"hash": "0" * 64}
    response = await client.post(
        "/api/v1/me/identities/telegram", json=payload, headers=headers(user)
    )
    assert response.status_code == 401


async def test_link_email_enables_password_login(client, cleanup, telegram_id):
    user = await create_user(cleanup, providers=[(AuthProvider.telegram, str(telegram_id))])
    address = email_address().upper()
    response = await client.post(
        "/api/v1/me/identities/email",
        json={"email": address, "password": PASSWORD},
        headers=headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == address.lower()
    assert body["email_verified"] is False
    assert sorted(item["provider"] for item in body["identities"]) == ["email", "telegram"]
    login = await client.post("/api/v1/auth/login", json={"email": address, "password": PASSWORD})
    assert login.status_code == 200


async def test_link_email_taken_conflicts(client, cleanup):
    address = email_address()
    await create_user(cleanup, email=address, password_hash=hash_password(PASSWORD))
    user = await create_user(cleanup)
    response = await client.post(
        "/api/v1/me/identities/email",
        json={"email": address, "password": PASSWORD},
        headers=headers(user),
    )
    assert response.status_code == 409


async def test_link_email_when_account_has_email_conflicts(client, cleanup):
    user = await create_user(cleanup, email=email_address())
    response = await client.post(
        "/api/v1/me/identities/email",
        json={"email": email_address(), "password": PASSWORD},
        headers=headers(user),
    )
    assert response.status_code == 409


async def test_unlink_telegram_keeps_other_identity(client, cleanup, telegram_id):
    address = email_address()
    user = await create_user(
        cleanup,
        email=address,
        telegram_chat_id=telegram_id,
        providers=[(AuthProvider.email, address), (AuthProvider.telegram, str(telegram_id))],
    )
    response = await client.delete("/api/v1/me/identities/telegram", headers=headers(user))
    assert response.status_code == 200
    assert [item["provider"] for item in response.json()["identities"]] == ["email"]
    async with SessionLocal() as session:
        stored = await session.get(User, user.id)
        assert stored.telegram_chat_id is None


async def test_unlink_email_clears_credentials(client, cleanup, telegram_id):
    address = email_address()
    user = await create_user(
        cleanup,
        email=address,
        password_hash=hash_password(PASSWORD),
        providers=[(AuthProvider.email, address), (AuthProvider.telegram, str(telegram_id))],
    )
    response = await client.delete("/api/v1/me/identities/email", headers=headers(user))
    assert response.status_code == 200
    assert response.json()["email"] is None
    login = await client.post("/api/v1/auth/login", json={"email": address, "password": PASSWORD})
    assert login.status_code == 401


async def test_unlink_last_identity_forbidden(client, cleanup, telegram_id):
    user = await create_user(cleanup, providers=[(AuthProvider.telegram, str(telegram_id))])
    response = await client.delete("/api/v1/me/identities/telegram", headers=headers(user))
    assert response.status_code == 409


async def test_unlink_missing_identity_not_found(client, cleanup, telegram_id):
    user = await create_user(cleanup, providers=[(AuthProvider.telegram, str(telegram_id))])
    response = await client.delete("/api/v1/me/identities/email", headers=headers(user))
    assert response.status_code == 404


async def test_accept_ai_transfer_records_time_once(client, cleanup):
    user = await create_user(cleanup)
    first = await client.post("/api/v1/me/consents/ai-transfer", headers=headers(user))
    assert first.status_code == 200
    accepted_at = first.json()["ai_transfer_accepted_at"]
    assert accepted_at is not None
    second = await client.post("/api/v1/me/consents/ai-transfer", headers=headers(user))
    assert second.json()["ai_transfer_accepted_at"] == accepted_at


async def test_revoke_ai_transfer_clears_consent(client, cleanup):
    user = await create_user(cleanup)
    await client.post("/api/v1/me/consents/ai-transfer", headers=headers(user))
    response = await client.delete("/api/v1/me/consents/ai-transfer", headers=headers(user))
    assert response.status_code == 200
    assert response.json()["ai_transfer_accepted_at"] is None
    me = await client.get("/api/v1/me", headers=headers(user))
    assert me.json()["ai_transfer_accepted_at"] is None
    again = await client.post("/api/v1/me/consents/ai-transfer", headers=headers(user))
    assert again.json()["ai_transfer_accepted_at"] is not None


async def test_previous_ai_transfer_revision_stays_consent(client, cleanup):
    user = await create_user(cleanup)
    first = await client.post("/api/v1/me/consents/ai-transfer", headers=headers(user))
    async with SessionLocal() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(ai_transfer_revision=date(2020, 1, 1))
        )
        await session.commit()
    me = await client.get("/api/v1/me", headers=headers(user))
    assert me.json()["ai_transfer_accepted_at"] == first.json()["ai_transfer_accepted_at"]


def webapp_init_data(telegram_id: int, **overrides) -> str:
    fields = {
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps({"id": telegram_id, "first_name": "Иван"}, ensure_ascii=False),
        "auth_date": str(int(time.time())),
    }
    fields.update(overrides)
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


async def identity_owner(telegram_id: int) -> uuid.UUID | None:
    async with SessionLocal() as session:
        return await session.scalar(
            select(AuthIdentity.user_id).where(
                AuthIdentity.provider == AuthProvider.telegram,
                AuthIdentity.provider_user_id == str(telegram_id),
            )
        )


async def test_link_telegram_by_init_data(client, cleanup, telegram_id):
    user = await create_user(cleanup, email=email_address())
    response = await client.post(
        "/api/v1/me/identities/telegram",
        json={"telegram_init_data": webapp_init_data(telegram_id)},
        headers=headers(user),
    )
    assert response.status_code == 200
    assert [item["provider"] for item in response.json()["identities"]] == ["telegram"]
    assert await identity_owner(telegram_id) == user.id
    async with SessionLocal() as session:
        assert (await session.get(User, user.id)).telegram_chat_id == telegram_id


async def test_link_telegram_by_init_data_rejects_forged_hash(client, cleanup, telegram_id):
    user = await create_user(cleanup)
    forged = webapp_init_data(telegram_id) + "0"
    response = await client.post(
        "/api/v1/me/identities/telegram",
        json={"telegram_init_data": forged},
        headers=headers(user),
    )
    assert response.status_code == 401
    assert await identity_owner(telegram_id) is None


async def test_link_telegram_requires_some_credentials(client, cleanup):
    user = await create_user(cleanup)
    response = await client.post("/api/v1/me/identities/telegram", json={}, headers=headers(user))
    assert response.status_code == 422


async def test_link_telegram_merges_empty_account(client, cleanup, telegram_id):
    empty = await create_user(
        cleanup, providers=[(AuthProvider.telegram, str(telegram_id))], telegram_chat_id=telegram_id
    )
    user = await create_user(cleanup, email=email_address())
    response = await client.post(
        "/api/v1/me/identities/telegram",
        json={"telegram_init_data": webapp_init_data(telegram_id)},
        headers=headers(user),
    )
    assert response.status_code == 200
    assert await identity_owner(telegram_id) == user.id
    async with SessionLocal() as session:
        assert await session.get(User, empty.id) is None
        assert (await session.get(User, user.id)).telegram_chat_id == telegram_id


async def test_link_telegram_merges_empty_account_by_widget(client, cleanup, telegram_id):
    empty = await create_user(cleanup, providers=[(AuthProvider.telegram, str(telegram_id))])
    user = await create_user(cleanup)
    response = await client.post(
        "/api/v1/me/identities/telegram", json=signed(telegram_id), headers=headers(user)
    )
    assert response.status_code == 200
    async with SessionLocal() as session:
        assert await session.get(User, empty.id) is None


async def test_link_telegram_keeps_account_with_lecture(client, cleanup, telegram_id):
    owner = await create_user(cleanup, providers=[(AuthProvider.telegram, str(telegram_id))])
    async with SessionLocal() as session:
        session.add(Lecture(owner_id=owner.id, title="Лекция", source_type=SourceType.upload))
        await session.commit()
    user = await create_user(cleanup)
    response = await client.post(
        "/api/v1/me/identities/telegram",
        json={"telegram_init_data": webapp_init_data(telegram_id)},
        headers=headers(user),
    )
    assert response.status_code == 409
    assert "Выйдите" in response.json()["detail"]
    assert await identity_owner(telegram_id) == owner.id


async def test_link_telegram_keeps_account_with_course(client, cleanup, telegram_id):
    owner = await create_user(cleanup, providers=[(AuthProvider.telegram, str(telegram_id))])
    async with SessionLocal() as session:
        session.add(Course(owner_id=owner.id, title="Курс"))
        await session.commit()
    user = await create_user(cleanup)
    response = await client.post(
        "/api/v1/me/identities/telegram",
        json={"telegram_init_data": webapp_init_data(telegram_id)},
        headers=headers(user),
    )
    assert response.status_code == 409
    assert await identity_owner(telegram_id) == owner.id


async def test_link_telegram_keeps_account_with_subscription(client, cleanup, telegram_id):
    owner = await create_user(cleanup, providers=[(AuthProvider.telegram, str(telegram_id))])
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        session.add(Subscription(user_id=owner.id, starts_at=now, ends_at=now + timedelta(days=30)))
        await session.commit()
    user = await create_user(cleanup)
    response = await client.post(
        "/api/v1/me/identities/telegram",
        json={"telegram_init_data": webapp_init_data(telegram_id)},
        headers=headers(user),
    )
    assert response.status_code == 409
    assert await identity_owner(telegram_id) == owner.id


async def test_link_telegram_keeps_account_with_email(client, cleanup, telegram_id):
    owner = await create_user(
        cleanup,
        email=email_address(),
        providers=[(AuthProvider.telegram, str(telegram_id))],
    )
    user = await create_user(cleanup)
    response = await client.post(
        "/api/v1/me/identities/telegram",
        json={"telegram_init_data": webapp_init_data(telegram_id)},
        headers=headers(user),
    )
    assert response.status_code == 409
    assert await identity_owner(telegram_id) == owner.id


async def test_link_email_taken_hints_to_relogin_for_telegram_account(client, cleanup, telegram_id):
    address = email_address()
    await create_user(cleanup, email=address, password_hash=hash_password(PASSWORD))
    user = await create_user(cleanup, providers=[(AuthProvider.telegram, str(telegram_id))])
    response = await client.post(
        "/api/v1/me/identities/email",
        json={"email": address, "password": PASSWORD},
        headers=headers(user),
    )
    assert response.status_code == 409
    assert "войдите по этой почте" in response.json()["detail"]


async def test_link_telegram_with_second_telegram_keeps_empty_account(client, cleanup, telegram_id):
    other = await create_user(cleanup, providers=[(AuthProvider.telegram, str(telegram_id + 1))])
    user = await create_user(cleanup, providers=[(AuthProvider.telegram, str(telegram_id))])
    response = await client.post(
        "/api/v1/me/identities/telegram",
        json={"telegram_init_data": webapp_init_data(telegram_id + 1)},
        headers=headers(user),
    )
    assert response.status_code == 409
    assert await identity_owner(telegram_id + 1) == other.id
