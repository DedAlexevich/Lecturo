import logging
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select, update

from app.api.auth import issue_and_send_password_reset
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging
from app.main import app
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


async def test_mail_without_smtp_hides_token_and_address_on_public_host(caplog, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("PUBLIC_URL", "https://lecturo.test/")
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    get_settings.cache_clear()
    with caplog.at_level("INFO", logger="app.services.mail"):
        await send_verification_mail("alice@example.org", "secret-token")
    get_settings.cache_clear()
    assert "Подтверждение почты в Lecturo" in caplog.text
    assert "a***@example.org" in caplog.text
    assert "secret-token" not in caplog.text
    assert "alice@example.org" not in caplog.text


async def test_mail_without_smtp_shows_body_locally(caplog, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("PUBLIC_URL", "http://localhost:5173")
    get_settings.cache_clear()
    with caplog.at_level("INFO", logger="app.services.mail"):
        await send_verification_mail("alice@example.org", "abc")
    get_settings.cache_clear()
    assert "http://localhost:5173/verify-email?token=abc" in caplog.text


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


async def test_stranger_cannot_exhaust_owner_reset_limit(client, email, mails):
    await register(client, email)
    transport = ASGITransport(app=app, client=("203.0.113.7", 1234))
    async with AsyncClient(transport=transport, base_url="http://test") as stranger:
        statuses = [
            (
                await stranger.post(f"{API}/password-reset/request", json={"email": email})
            ).status_code
            for _ in range(4)
        ]
    assert statuses == [204, 204, 204, 429]

    response = await client.post(f"{API}/password-reset/request", json={"email": email})

    assert response.status_code == 204
    assert len(mails) == 4


async def test_rejected_by_ip_does_not_consume_address_limit(client, email, mails, monkeypatch):
    monkeypatch.setenv("AUTH_MAIL_IP_RATE_LIMIT", "1")
    get_settings.cache_clear()
    try:
        first = await client.post(f"{API}/password-reset/request", json={"email": email})
        second = await client.post(f"{API}/password-reset/request", json={"email": email})
    finally:
        get_settings.cache_clear()
    redis = Redis.from_url(get_settings().redis_url)
    counters = [int(await redis.get(key)) for key in await redis.keys("rate:auth-mail:subject:*")]
    await redis.aclose()

    assert (first.status_code, second.status_code) == (204, 429)
    assert counters == [1]


async def test_mail_delivery_failure_is_logged(caplog, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.invalid")
    get_settings.cache_clear()

    def broken(message):
        raise OSError("connection refused")

    monkeypatch.setattr("app.services.mail.deliver", broken)
    try:
        with caplog.at_level("ERROR", logger="app.services.mail"):
            await send_verification_mail("alice@example.org", "abc")
    finally:
        get_settings.cache_clear()

    assert "Не удалось отправить письмо" in caplog.text
    assert "alice@example.org" not in caplog.text


async def test_reset_task_failure_is_logged(client, email, caplog, monkeypatch):
    await register(client, email)

    async def broken(to, token):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.api.auth.send_password_reset_mail", broken)

    with caplog.at_level("ERROR", logger="app.api.auth"):
        await issue_and_send_password_reset(email)

    assert "Не удалось выдать и отправить ссылку сброса пароля" in caplog.text


async def test_address_total_limit_caps_requests_from_many_ips(email, mails, monkeypatch):
    monkeypatch.setenv("AUTH_MAIL_ADDRESS_RATE_LIMIT", "4")
    get_settings.cache_clear()
    statuses = []
    try:
        for i in range(6):
            transport = ASGITransport(app=app, client=(f"203.0.113.{i}", 1234))
            async with AsyncClient(transport=transport, base_url="http://test") as other:
                response = await other.post(f"{API}/password-reset/request", json={"email": email})
                statuses.append(response.status_code)
    finally:
        get_settings.cache_clear()
    assert statuses == [204, 204, 204, 204, 429, 429]


async def test_mail_without_smtp_logged_at_info(caplog, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("PUBLIC_URL", "http://localhost")
    get_settings.cache_clear()
    with caplog.at_level("INFO", logger="app"):
        await send_verification_mail("a@example.org", "abc")
    get_settings.cache_clear()
    records = [r for r in caplog.records if r.name == "app.services.mail"]
    assert [r.levelname for r in records] == ["INFO"]
    assert "verify-email?token=abc" in records[0].getMessage()


def test_app_logger_writes_info_to_stdout(capsys):
    logger = logging.getLogger("app")
    saved_handlers, saved_level = logger.handlers[:], logger.level
    logger.handlers.clear()
    try:
        configure_logging()
        configure_logging()
        logging.getLogger("app.services.mail").info("письмо в лог")
    finally:
        logger.handlers[:] = saved_handlers
        logger.setLevel(saved_level)
    assert capsys.readouterr().out.count("письмо в лог") == 1
