import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete

from app.core.db import SessionLocal
from app.models import User


@pytest.fixture
async def email() -> AsyncIterator[str]:
    address = f"user-{uuid.uuid4().hex[:8]}@example.org"
    yield address
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.email == address))
        await session.commit()


def register_body(email: str, **overrides) -> dict:
    return {"email": email, "password": "секретный-пароль", "accept_terms": True, **overrides}


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
