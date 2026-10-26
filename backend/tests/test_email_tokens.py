import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import AuthToken, User
from app.services.mail import send_verification_mail
from tests.test_auth import register_body

API = "/api/v1/auth"


@pytest.fixture
async def email() -> AsyncIterator[str]:
    address = f"user-{uuid.uuid4().hex[:8]}@example.org"
    yield address
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.email == address))
        await session.commit()


@pytest.fixture
def mails(monkeypatch):
    sent = []

    async def capture(to, subject, body):
        sent.append((to, subject, body))

    monkeypatch.setattr("app.services.mail.send_mail", capture)
    return sent


def extract_token(body: str, path: str) -> str:
    match = re.search(rf"/{path}\?token=(\S+)", body)
    assert match
    return match.group(1)


async def register(client, email):
    response = await client.post(f"{API}/register", json=register_body(email))
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def expire_tokens(email):
    async with SessionLocal() as session:
        user_id = await session.scalar(select(User.id).where(User.email == email))
        await session.execute(
            update(AuthToken)
            .where(AuthToken.user_id == user_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()


async def test_verify_email_flow(client, email, mails):
    headers = await register(client, email)

    requested = await client.post(f"{API}/verify-email/request", headers=headers)
    assert requested.status_code == 204
    to, _, body = mails[0]
    assert to == email
    token = extract_token(body, "verify-email")

    confirmed = await client.post(f"{API}/verify-email/confirm", json={"token": token})
    assert confirmed.status_code == 204
    me = await client.get("/api/v1/me", headers=headers)
    assert me.json()["email_verified"] is True

    reused = await client.post(f"{API}/verify-email/confirm", json={"token": token})
    assert reused.status_code == 400

    again = await client.post(f"{API}/verify-email/request", headers=headers)
    assert again.status_code == 204
    assert len(mails) == 1


async def test_verify_email_requires_auth_and_email(client, auth_headers, mails):
    assert (await client.post(f"{API}/verify-email/request")).status_code == 401
    response = await client.post(f"{API}/verify-email/request", headers=auth_headers)
    assert response.status_code == 400
    assert mails == []


async def test_verify_email_expired_and_unknown_token(client, email, mails):
    headers = await register(client, email)
    await client.post(f"{API}/verify-email/request", headers=headers)
    token = extract_token(mails[0][2], "verify-email")
    await expire_tokens(email)

    expired = await client.post(f"{API}/verify-email/confirm", json={"token": token})
    unknown = await client.post(f"{API}/verify-email/confirm", json={"token": "нет-такого"})
    assert expired.status_code == 400
    assert unknown.status_code == 400


async def test_new_request_invalidates_previous_token(client, email, mails):
    headers = await register(client, email)
    await client.post(f"{API}/verify-email/request", headers=headers)
    await client.post(f"{API}/verify-email/request", headers=headers)
    first = extract_token(mails[0][2], "verify-email")
    second = extract_token(mails[1][2], "verify-email")

    stale = await client.post(f"{API}/verify-email/confirm", json={"token": first})
    fresh = await client.post(f"{API}/verify-email/confirm", json={"token": second})
    assert stale.status_code == 400
    assert fresh.status_code == 204


async def test_password_reset_flow(client, email, mails):
    await register(client, email)

    requested = await client.post(f"{API}/password-reset/request", json={"email": email.upper()})
    assert requested.status_code == 204
    token = extract_token(mails[0][2], "reset-password")

    confirmed = await client.post(
        f"{API}/password-reset/confirm", json={"token": token, "password": "новый-пароль-1"}
    )
    assert confirmed.status_code == 204

    old = await client.post(f"{API}/login", json={"email": email, "password": "секретный-пароль"})
    new = await client.post(f"{API}/login", json={"email": email, "password": "новый-пароль-1"})
    assert old.status_code == 401
    assert new.status_code == 200

    reused = await client.post(
        f"{API}/password-reset/confirm", json={"token": token, "password": "третий-пароль-1"}
    )
    assert reused.status_code == 400


async def test_password_reset_unknown_email_looks_the_same(client, email, mails):
    await register(client, email)
    known = await client.post(f"{API}/password-reset/request", json={"email": email})
    unknown = await client.post(f"{API}/password-reset/request", json={"email": f"missing-{email}"})
    assert known.status_code == unknown.status_code == 204
    assert known.content == unknown.content
    assert len(mails) == 1


async def test_password_reset_token_expires(client, email, mails):
    await register(client, email)
    await client.post(f"{API}/password-reset/request", json={"email": email})
    token = extract_token(mails[0][2], "reset-password")
    await expire_tokens(email)

    response = await client.post(
        f"{API}/password-reset/confirm", json={"token": token, "password": "новый-пароль-1"}
    )
    assert response.status_code == 400


async def test_verify_token_does_not_reset_password(client, email, mails):
    headers = await register(client, email)
    await client.post(f"{API}/verify-email/request", headers=headers)
    token = extract_token(mails[0][2], "verify-email")

    response = await client.post(
        f"{API}/password-reset/confirm", json={"token": token, "password": "новый-пароль-1"}
    )
    assert response.status_code == 400


async def test_mail_without_smtp_goes_to_log(caplog, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("PUBLIC_URL", "https://lecturo.test/")
    get_settings.cache_clear()
    with caplog.at_level("INFO", logger="app.services.mail"):
        await send_verification_mail("a@example.org", "abc")
    get_settings.cache_clear()
    assert "https://lecturo.test/verify-email?token=abc" in caplog.text


@pytest.fixture(autouse=True)
async def clean_mail_limits():
    redis = Redis.from_url(get_settings().redis_url)
    for key in await redis.keys("rate:auth-mail:*"):
        await redis.delete(key)
    await redis.aclose()


async def test_password_reset_rate_limited_per_email(client, email, mails):
    await register(client, email)
    statuses = [
        (await client.post(f"{API}/password-reset/request", json={"email": email})).status_code
        for _ in range(4)
    ]
    assert statuses == [204, 204, 204, 429]
    assert len(mails) == 3


async def test_password_reset_limit_same_for_unknown_email(client, email, mails):
    unknown = f"missing-{email}"
    responses = [
        await client.post(f"{API}/password-reset/request", json={"email": unknown})
        for _ in range(4)
    ]
    assert [r.status_code for r in responses] == [204, 204, 204, 429]
    assert not mails


async def test_password_reset_rate_limited_per_ip(client, mails, monkeypatch):
    monkeypatch.setenv("AUTH_MAIL_IP_RATE_LIMIT", "2")
    get_settings.cache_clear()
    try:
        statuses = [
            (
                await client.post(
                    f"{API}/password-reset/request", json={"email": f"a{i}@example.org"}
                )
            ).status_code
            for i in range(3)
        ]
    finally:
        get_settings.cache_clear()
    assert statuses == [204, 204, 429]


async def test_verify_email_rate_limited(client, email, mails):
    headers = await register(client, email)
    statuses = [
        (await client.post(f"{API}/verify-email/request", headers=headers)).status_code
        for _ in range(4)
    ]
    assert statuses == [204, 204, 204, 429]
    assert len(mails) == 3
