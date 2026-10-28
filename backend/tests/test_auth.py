import hashlib
import uuid
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import User
from app.services.legal import read_document

pytestmark = pytest.mark.usefixtures("reset_auth_rate_limits")


@pytest.fixture
async def email() -> AsyncIterator[str]:
    address = f"user-{uuid.uuid4().hex[:8]}@example.org"
    yield address
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.email == address))
        await session.commit()
    digest = hashlib.sha256(address.encode()).hexdigest()
    redis = Redis.from_url(get_settings().redis_url)
    await redis.delete(f"rate:login:email:{digest}")
    await redis.aclose()


def register_body(email: str, **overrides) -> dict:
    return {
        "email": email,
        "password": "секретный-пароль",
        "accept_terms": True,
        "accept_personal_data": True,
        **overrides,
    }


async def test_register_login_and_me(client, email):
    registered = await client.post("/api/v1/auth/register", json=register_body(email))
    assert registered.status_code == 201
    assert registered.json()["token_type"] == "bearer"

    logged_in = await client.post(
        "/api/v1/auth/login", json={"email": email.upper(), "password": "секретный-пароль"}
    )
    assert logged_in.status_code == 200
    token = logged_in.json()["access_token"]

    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == email
    assert body["email_verified"] is False
    assert [identity["provider"] for identity in body["identities"]] == ["email"]


async def test_register_requires_terms(client, email):
    response = await client.post(
        "/api/v1/auth/register", json=register_body(email, accept_terms=False)
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "accept_terms"]


async def test_register_requires_personal_data_consent(client, email):
    response = await client.post(
        "/api/v1/auth/register", json=register_body(email, accept_personal_data=False)
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "accept_personal_data"]
    async with SessionLocal() as session:
        assert await session.scalar(select(User).where(User.email == email)) is None


async def test_register_stores_consents(client, email):
    response = await client.post("/api/v1/auth/register", json=register_body(email))
    assert response.status_code == 201
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == email))
    assert user.terms_accepted_at is not None
    assert user.personal_data_accepted_at is not None
    assert user.terms_revision == read_document("terms").revision_date
    assert user.personal_data_revision == read_document("personal-data-consent").revision_date


async def test_register_duplicate_email(client, email):
    first = await client.post("/api/v1/auth/register", json=register_body(email))
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/register", json=register_body(email.upper()))
    assert second.status_code == 409


async def test_login_wrong_password_and_unknown_email(client, email):
    await client.post("/api/v1/auth/register", json=register_body(email))

    wrong_password = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "другой-пароль"}
    )
    unknown_email = await client.post(
        "/api/v1/auth/login",
        json={"email": f"missing-{email}", "password": "секретный-пароль"},
    )
    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


async def test_me_requires_auth(client):
    response = await client.get("/api/v1/me")
    assert response.status_code == 401


async def login(client, email: str, password: str) -> int:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response.status_code


async def test_login_is_rate_limited_per_email(client, email, monkeypatch):
    await client.post("/api/v1/auth/register", json=register_body(email))
    monkeypatch.setattr(get_settings(), "login_rate_limit", 2)
    statuses = [
        await login(client, email, "другой-пароль"),
        await login(client, email.upper(), "другой-пароль"),
        await login(client, email, "секретный-пароль"),
    ]
    assert statuses == [401, 401, 429]


async def test_successful_login_resets_email_limit(client, email, monkeypatch):
    await client.post("/api/v1/auth/register", json=register_body(email))
    monkeypatch.setattr(get_settings(), "login_rate_limit", 2)
    statuses = [
        await login(client, email, "другой-пароль"),
        await login(client, email, "секретный-пароль"),
        await login(client, email, "другой-пароль"),
        await login(client, email, "другой-пароль"),
        await login(client, email, "другой-пароль"),
    ]
    assert statuses == [401, 200, 401, 401, 429]


async def test_login_ip_limit_counts_only_failures(client, email, monkeypatch):
    await client.post("/api/v1/auth/register", json=register_body(email))
    monkeypatch.setattr(get_settings(), "login_ip_rate_limit", 2)
    redis = Redis.from_url(get_settings().redis_url)
    unknown = [f"{index}-{email}" for index in range(2)]
    try:
        statuses = [await login(client, email, "секретный-пароль") for _ in range(3)]
        statuses += [await login(client, address, "секретный-пароль") for address in unknown]
        statuses.append(await login(client, email, "секретный-пароль"))
    finally:
        for address in unknown:
            digest = hashlib.sha256(address.encode()).hexdigest()
            await redis.delete(f"rate:login:email:{digest}")
        await redis.aclose()
    assert statuses == [200, 200, 200, 401, 401, 429]


async def test_login_rejects_too_long_password(client, email):
    assert await login(client, email, "x" * 129) == 422


async def test_register_ip_limit_counts_only_failures(client, email, monkeypatch):
    monkeypatch.setattr(get_settings(), "register_rate_limit", 2)
    second = f"second-{email}"
    try:
        statuses = [
            (await client.post("/api/v1/auth/register", json=register_body(address))).status_code
            for address in (email, second, email, email.upper(), f"third-{email}")
        ]
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(User).where(User.email == second))
            await session.commit()
    assert statuses == [201, 201, 409, 409, 429]


async def test_providers_expose_telegram_bot_id(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "123456789:AAEhBP0av28")
    assert (await client.get("/api/v1/auth/providers")).json()["telegram_bot_id"] == 123456789
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "")
    assert (await client.get("/api/v1/auth/providers")).json()["telegram_bot_id"] is None
