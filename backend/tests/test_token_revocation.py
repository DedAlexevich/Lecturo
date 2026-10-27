import random
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import ALGORITHM, create_access_token, decode_access_token
from app.models import AuthIdentity, AuthProvider, AuthToken, AuthTokenKind, User
from app.services.auth_tokens import issue_token
from tests.test_auth import register_body
from tests.test_email_tokens import extract_token

API = "/api/v1"
PASSWORD = "секретный-пароль"
NEW_PASSWORD = "новый-пароль-1"


@pytest.fixture
async def emails() -> AsyncIterator[list[str]]:
    created: list[str] = []
    yield created
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.email.in_(created)))
        await session.commit()


@pytest.fixture
def mails(monkeypatch):
    sent = []

    async def capture(to, subject, body):
        sent.append((to, subject, body))

    monkeypatch.setattr("app.services.mail.send_mail", capture)
    return sent


@pytest.fixture(autouse=True)
async def clean_limits():
    redis = Redis.from_url(get_settings().redis_url)
    for pattern in ("rate:auth-mail:*", "rate:password-change:*"):
        for key in await redis.keys(pattern):
            await redis.delete(key)
    await redis.aclose()


def new_email(emails: list[str]) -> str:
    address = f"revoke-{uuid.uuid4().hex[:8]}@example.org"
    emails.append(address)
    return address


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(client, email: str) -> dict[str, str]:
    response = await client.post(f"{API}/auth/register", json=register_body(email))
    return bearer(response.json()["access_token"])


async def user_by_email(email: str) -> User:
    async with SessionLocal() as session:
        return await session.scalar(select(User).where(User.email == email))


async def add_telegram(user_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        session.add(
            AuthIdentity(
                user_id=user_id,
                provider=AuthProvider.telegram,
                provider_user_id=str(random.randint(10**9, 10**10)),
            )
        )
        await session.commit()


async def me_status(client, headers: dict[str, str]) -> int:
    return (await client.get(f"{API}/me", headers=headers)).status_code


def test_token_carries_version():
    user_id = uuid.uuid4()
    grant = decode_access_token(create_access_token(user_id, 3))
    assert grant is not None
    assert (grant.user_id, grant.version) == (user_id, 3)


def test_token_with_broken_version_is_rejected():
    payload = {"sub": str(uuid.uuid4()), "ver": "1", "exp": datetime.now(UTC) + timedelta(hours=1)}
    token = jwt.encode(payload, get_settings().secret_key, algorithm=ALGORITHM)
    assert decode_access_token(token) is None


async def test_token_without_version_counts_as_zero(client, user):
    payload = {"sub": str(user.id), "exp": datetime.now(UTC) + timedelta(hours=1)}
    legacy = jwt.encode(payload, get_settings().secret_key, algorithm=ALGORITHM)
    assert await me_status(client, bearer(legacy)) == 200

    async with SessionLocal() as session:
        await session.execute(update(User).where(User.id == user.id).values(token_version=1))
        await session.commit()
    assert await me_status(client, bearer(legacy)) == 401


async def test_change_password_revokes_old_tokens(client, emails):
    email = new_email(emails)
    old = await register(client, email)
    other_device = bearer(
        (
            await client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
        ).json()["access_token"]
    )

    response = await client.post(
        f"{API}/me/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=old,
    )

    assert response.status_code == 200
    assert await me_status(client, old) == 401
    assert await me_status(client, other_device) == 401
    assert await me_status(client, bearer(response.json()["access_token"])) == 200
    login = await client.post(f"{API}/auth/login", json={"email": email, "password": NEW_PASSWORD})
    assert await me_status(client, bearer(login.json()["access_token"])) == 200


async def test_password_reset_revokes_tokens_and_verifies_email(client, emails, mails):
    email = new_email(emails)
    old = await register(client, email)
    await client.post(f"{API}/auth/password-reset/request", json={"email": email})
    token = extract_token(mails[0][2], "reset-password")

    response = await client.post(
        f"{API}/auth/password-reset/confirm", json={"token": token, "password": NEW_PASSWORD}
    )

    assert response.status_code == 204
    assert await me_status(client, old) == 401
    login = await client.post(f"{API}/auth/login", json={"email": email, "password": NEW_PASSWORD})
    fresh = bearer(login.json()["access_token"])
    me = await client.get(f"{API}/me", headers=fresh)
    assert me.status_code == 200
    assert me.json()["email_verified"] is True


async def test_password_reset_keeps_earlier_verification_time(client, emails, mails):
    email = new_email(emails)
    await register(client, email)
    verified_at = datetime.now(UTC) - timedelta(days=10)
    async with SessionLocal() as session:
        await session.execute(
            update(User).where(User.email == email).values(email_verified_at=verified_at)
        )
        await session.commit()
    await client.post(f"{API}/auth/password-reset/request", json={"email": email})
    token = extract_token(mails[0][2], "reset-password")

    await client.post(
        f"{API}/auth/password-reset/confirm", json={"token": token, "password": NEW_PASSWORD}
    )

    assert (await user_by_email(email)).email_verified_at == verified_at


async def test_unlink_revokes_old_tokens_and_returns_new_one(client, emails):
    email = new_email(emails)
    old = await register(client, email)
    user = await user_by_email(email)
    await add_telegram(user.id)

    response = await client.delete(f"{API}/me/identities/telegram", headers=old)

    assert response.status_code == 200
    assert await me_status(client, old) == 401
    assert await me_status(client, bearer(response.headers["X-Access-Token"])) == 200


async def test_old_verify_token_does_not_confirm_relinked_email(client, emails, mails):
    first = new_email(emails)
    headers = await register(client, first)
    user = await user_by_email(first)
    await add_telegram(user.id)
    await client.post(f"{API}/auth/verify-email/request", headers=headers)
    token = extract_token(mails[0][2], "verify-email")

    unlinked = await client.delete(f"{API}/me/identities/email", headers=headers)
    headers = bearer(unlinked.headers["X-Access-Token"])
    second = new_email(emails)
    linked = await client.post(
        f"{API}/me/identities/email",
        json={"email": second, "password": PASSWORD},
        headers=headers,
    )
    assert linked.status_code == 200

    response = await client.post(f"{API}/auth/verify-email/confirm", json={"token": token})

    assert response.status_code == 400
    me = await client.get(f"{API}/me", headers=headers)
    assert me.json()["email"] == second
    assert me.json()["email_verified"] is False


async def test_link_email_removes_unused_tokens(client, user):
    async with SessionLocal() as session:
        session.add(
            AuthToken(
                user_id=user.id,
                kind=AuthTokenKind.verify_email,
                token_hash=uuid.uuid4().hex,
                email="old@example.org",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()
    address = f"link-{uuid.uuid4().hex[:8]}@example.org"

    response = await client.post(
        f"{API}/me/identities/email",
        json={"email": address, "password": PASSWORD},
        headers=bearer(create_access_token(user.id, user.token_version)),
    )

    assert response.status_code == 200
    async with SessionLocal() as session:
        left = await session.scalars(select(AuthToken.id).where(AuthToken.user_id == user.id))
        assert left.all() == []


async def test_token_is_bound_to_address(client, emails):
    first = new_email(emails)
    await register(client, first)
    user = await user_by_email(first)
    async with SessionLocal() as session:
        token = await issue_token(session, user.id, first, AuthTokenKind.verify_email)
    second = new_email(emails)
    async with SessionLocal() as session:
        await session.execute(update(User).where(User.id == user.id).values(email=second))
        await session.commit()

    response = await client.post(f"{API}/auth/verify-email/confirm", json={"token": token})

    assert response.status_code == 400
    assert (await user_by_email(second)).email_verified_at is None
