import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import AuthToken, AuthTokenKind, User
from app.services.auth import hash_password, verify_password
from app.services.auth_tokens import issue_token

PASSWORD = "старый-пароль"
NEW_PASSWORD = "новый-пароль-1"


@pytest.fixture
async def account() -> AsyncIterator[User]:
    async with SessionLocal() as session:
        user = User(
            email=f"profile-{uuid.uuid4().hex[:8]}@example.org",
            password_hash=hash_password(PASSWORD),
            display_name="Старое имя",
        )
        session.add(user)
        await session.commit()
        yield user
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}


async def stored_hash(user: User) -> str | None:
    async with SessionLocal() as session:
        return await session.scalar(select(User.password_hash).where(User.id == user.id))


async def test_update_display_name(client, account):
    response = await client.patch(
        "/api/v1/me", json={"display_name": "  Новое имя  "}, headers=headers(account)
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Новое имя"
    me = await client.get("/api/v1/me", headers=headers(account))
    assert me.json()["display_name"] == "Новое имя"


@pytest.mark.parametrize("name", ["", "   ", "я" * 121])
async def test_update_display_name_invalid(client, account, name):
    response = await client.patch(
        "/api/v1/me", json={"display_name": name}, headers=headers(account)
    )
    assert response.status_code == 422


async def test_update_display_name_requires_auth(client):
    response = await client.patch("/api/v1/me", json={"display_name": "Имя"})
    assert response.status_code == 401


async def test_change_password(client, account):
    response = await client.post(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers(account),
    )
    assert response.status_code == 200
    login = await client.post(
        "/api/v1/auth/login", json={"email": account.email, "password": NEW_PASSWORD}
    )
    assert login.status_code == 200
    old = await client.post(
        "/api/v1/auth/login", json={"email": account.email, "password": PASSWORD}
    )
    assert old.status_code == 401


async def test_change_password_wrong_current(client, account):
    response = await client.post(
        "/api/v1/me/password",
        json={"current_password": "не-тот-пароль", "new_password": NEW_PASSWORD},
        headers=headers(account),
    )
    assert response.status_code == 403
    assert verify_password(await stored_hash(account), PASSWORD)


async def test_change_password_missing_current(client, account):
    response = await client.post(
        "/api/v1/me/password", json={"new_password": NEW_PASSWORD}, headers=headers(account)
    )
    assert response.status_code == 403


async def test_change_password_too_short(client, account):
    response = await client.post(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": "коротко"},
        headers=headers(account),
    )
    assert response.status_code == 422
    assert verify_password(await stored_hash(account), PASSWORD)


async def test_set_password_without_existing(client, user):
    response = await client.post(
        "/api/v1/me/password", json={"new_password": NEW_PASSWORD}, headers=headers(user)
    )
    assert response.status_code == 200
    assert verify_password(await stored_hash(user), NEW_PASSWORD)


async def test_change_password_revokes_mail_tokens(client, account):
    async with SessionLocal() as session:
        for kind in AuthTokenKind:
            await issue_token(session, account.id, account.email, kind)
    response = await client.post(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers(account),
    )
    assert response.status_code == 200
    async with SessionLocal() as session:
        active = (
            await session.scalars(
                select(AuthToken).where(
                    AuthToken.user_id == account.id, AuthToken.used_at.is_(None)
                )
            )
        ).all()
    assert not active


async def test_change_password_rate_limited(client, account, monkeypatch):
    monkeypatch.setattr(get_settings(), "password_change_rate_limit", 2)
    monkeypatch.setattr(get_settings(), "password_change_rate_window_seconds", 60)
    payload = {"current_password": "не-тот-пароль", "new_password": NEW_PASSWORD}
    codes = []
    for _ in range(3):
        response = await client.post("/api/v1/me/password", json=payload, headers=headers(account))
        codes.append(response.status_code)
    assert codes == [403, 403, 429]
