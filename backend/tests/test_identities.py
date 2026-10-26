import hashlib
import hmac
import random
import time
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import AuthIdentity, AuthProvider, User
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
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


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
        cleanup, providers=[(AuthProvider.telegram, str(telegram_id))], telegram_chat_id=telegram_id
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
