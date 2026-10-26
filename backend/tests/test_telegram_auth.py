import hashlib
import hmac
import random
import time
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import AuthIdentity, AuthProvider, User

BOT_TOKEN = "123456:test-bot-token"


@pytest.fixture
def bot_token(monkeypatch) -> str:
    monkeypatch.setattr(get_settings(), "telegram_bot_token", BOT_TOKEN)
    return BOT_TOKEN


@pytest.fixture
async def telegram_id() -> AsyncIterator[int]:
    value = random.randint(10**9, 10**10)
    yield value
    async with SessionLocal() as session:
        user_ids = select(AuthIdentity.user_id).where(
            AuthIdentity.provider == AuthProvider.telegram,
            AuthIdentity.provider_user_id == str(value),
        )
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()


def signed(token: str, **fields) -> dict:
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hashlib.sha256(token.encode()).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return fields


async def test_login_creates_and_returns_same_user(client, bot_token, telegram_id):
    payload = signed(
        bot_token,
        id=telegram_id,
        first_name="Иван",
        last_name="Петров",
        username="ivan",
        auth_date=int(time.time()),
    )
    first = await client.post("/api/v1/auth/telegram", json=payload)
    assert first.status_code == 200
    second = await client.post("/api/v1/auth/telegram", json=payload)
    assert second.status_code == 200

    me_first = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {first.json()['access_token']}"}
    )
    me_second = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {second.json()['access_token']}"}
    )
    assert me_first.json()["id"] == me_second.json()["id"]
    assert me_first.json()["display_name"] == "Иван Петров"
    assert [identity["provider"] for identity in me_first.json()["identities"]] == ["telegram"]

    async with SessionLocal() as session:
        user = await session.get(User, me_first.json()["id"])
        assert user.telegram_chat_id == telegram_id


async def test_forged_hash_rejected(client, bot_token, telegram_id):
    payload = signed(
        "654321:other-token", id=telegram_id, first_name="Иван", auth_date=int(time.time())
    )
    response = await client.post("/api/v1/auth/telegram", json=payload)
    assert response.status_code == 401


async def test_changed_field_rejected(client, bot_token, telegram_id):
    payload = signed(bot_token, id=telegram_id, first_name="Иван", auth_date=int(time.time()))
    payload["first_name"] = "Пётр"
    response = await client.post("/api/v1/auth/telegram", json=payload)
    assert response.status_code == 401


async def test_expired_auth_date_rejected(client, bot_token, telegram_id):
    payload = signed(
        bot_token, id=telegram_id, first_name="Иван", auth_date=int(time.time()) - 2 * 86400
    )
    response = await client.post("/api/v1/auth/telegram", json=payload)
    assert response.status_code == 401


async def test_future_auth_date_rejected(client, bot_token, telegram_id):
    payload = signed(
        bot_token, id=telegram_id, first_name="Иван", auth_date=int(time.time()) + 3600
    )
    response = await client.post("/api/v1/auth/telegram", json=payload)
    assert response.status_code == 401


async def test_login_disabled_without_bot_token(client, monkeypatch, telegram_id):
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "")
    payload = signed("", id=telegram_id, first_name="Иван", auth_date=int(time.time()))
    response = await client.post("/api/v1/auth/telegram", json=payload)
    assert response.status_code == 503
