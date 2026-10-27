import hashlib
import hmac
import json
import random
import time
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import AuthIdentity, AuthProvider, User

BOT_TOKEN = "123456:test-bot-token"
URL = "/api/v1/auth/telegram-webapp"
CONSENTS = {"accept_terms": True, "accept_personal_data": True}


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


def init_data(token: str, **fields) -> str:
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def webapp_fields(telegram_id: int, **overrides) -> dict:
    user = {"id": telegram_id, "first_name": "Иван", "last_name": "Петров", "username": "ivan"}
    fields = {
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    fields.update(overrides)
    return fields


async def test_login_creates_and_returns_same_user(client, bot_token, telegram_id):
    payload = {"init_data": init_data(bot_token, **webapp_fields(telegram_id))}
    first = await client.post(URL, json={**payload, **CONSENTS})
    assert first.status_code == 200
    second = await client.post(URL, json=payload)
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


async def test_same_user_as_login_widget(client, bot_token, telegram_id):
    auth_date = int(time.time())
    widget_fields = {"id": telegram_id, "first_name": "Иван", "auth_date": auth_date}
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(widget_fields.items()))
    secret = hashlib.sha256(bot_token.encode()).digest()
    widget_fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    widget = await client.post("/api/v1/auth/telegram", json={**widget_fields, **CONSENTS})
    webapp = await client.post(
        URL, json={"init_data": init_data(bot_token, **webapp_fields(telegram_id))}
    )
    assert widget.status_code == 200
    assert webapp.status_code == 200

    me_widget = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {widget.json()['access_token']}"}
    )
    me_webapp = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {webapp.json()['access_token']}"}
    )
    assert me_widget.json()["id"] == me_webapp.json()["id"]


async def test_new_user_without_consents_not_created(client, bot_token, telegram_id):
    payload = {"init_data": init_data(bot_token, **webapp_fields(telegram_id))}
    response = await client.post(URL, json={**payload, "accept_terms": True})
    assert response.status_code == 403
    async with SessionLocal() as session:
        identity = await session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == AuthProvider.telegram,
                AuthIdentity.provider_user_id == str(telegram_id),
            )
        )
    assert identity is None


async def test_consents_saved_on_first_login(client, bot_token, telegram_id):
    payload = {"init_data": init_data(bot_token, **webapp_fields(telegram_id))}
    response = await client.post(URL, json={**payload, **CONSENTS})
    assert response.status_code == 200
    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).join(AuthIdentity).where(AuthIdentity.provider_user_id == str(telegram_id))
        )
    assert user.terms_accepted_at is not None
    assert user.personal_data_accepted_at is not None


async def test_forged_hash_rejected(client, bot_token, telegram_id):
    payload = {"init_data": init_data("654321:other-token", **webapp_fields(telegram_id))}
    response = await client.post(URL, json=payload)
    assert response.status_code == 401


async def test_widget_style_signature_rejected(client, bot_token, telegram_id):
    fields = webapp_fields(telegram_id)
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hashlib.sha256(bot_token.encode()).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    response = await client.post(URL, json={"init_data": urlencode(fields)})
    assert response.status_code == 401


async def test_changed_user_rejected(client, bot_token, telegram_id):
    signed = init_data(bot_token, **webapp_fields(telegram_id))
    forged = signed.replace(str(telegram_id), str(telegram_id + 1))
    response = await client.post(URL, json={"init_data": forged})
    assert response.status_code == 401


async def test_missing_hash_rejected(client, bot_token, telegram_id):
    response = await client.post(URL, json={"init_data": urlencode(webapp_fields(telegram_id))})
    assert response.status_code == 401


async def test_duplicate_field_rejected(client, bot_token, telegram_id):
    signed = init_data(bot_token, **webapp_fields(telegram_id))
    response = await client.post(URL, json={"init_data": f"{signed}&auth_date=1"})
    assert response.status_code == 401


async def test_missing_user_rejected(client, bot_token, telegram_id):
    fields = webapp_fields(telegram_id)
    del fields["user"]
    response = await client.post(URL, json={"init_data": init_data(bot_token, **fields)})
    assert response.status_code == 401


async def test_expired_auth_date_rejected(client, bot_token, telegram_id):
    fields = webapp_fields(telegram_id, auth_date=str(int(time.time()) - 2 * 86400))
    response = await client.post(URL, json={"init_data": init_data(bot_token, **fields)})
    assert response.status_code == 401


async def test_future_auth_date_rejected(client, bot_token, telegram_id):
    fields = webapp_fields(telegram_id, auth_date=str(int(time.time()) + 3600))
    response = await client.post(URL, json={"init_data": init_data(bot_token, **fields)})
    assert response.status_code == 401


async def test_login_disabled_without_bot_token(client, monkeypatch, telegram_id):
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "")
    response = await client.post(
        URL, json={"init_data": init_data("", **webapp_fields(telegram_id))}
    )
    assert response.status_code == 503

    response = await client.post(URL, json={"init_data": "user=%7B%7D"})
    assert response.status_code == 503
