import json
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import (
    AuthIdentity,
    AuthProvider,
    Lecture,
    Payment,
    PaymentKind,
    PaymentStatus,
    SourceType,
    User,
)
from app.services.auth import hash_password
from tests.test_telegram_auth import BOT_TOKEN, signed
from tests.test_telegram_webapp import init_data, webapp_fields

URL = "/api/v1/me/delete"
PASSWORD = "секретный-пароль"


@pytest.fixture
def storage(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path)
    return tmp_path


@pytest.fixture
def bot_token(monkeypatch) -> str:
    monkeypatch.setattr(get_settings(), "telegram_bot_token", BOT_TOKEN)
    return BOT_TOKEN


@pytest.fixture
async def account() -> AsyncIterator[User]:
    telegram_id = uuid.uuid4().int % 10**9 + 10**9
    address = f"delete-{uuid.uuid4().hex[:8]}@example.org"
    async with SessionLocal() as session:
        user = User(email=address, password_hash=hash_password(PASSWORD), display_name="Тест")
        user.identities.append(AuthIdentity(provider=AuthProvider.email, provider_user_id=address))
        user.identities.append(
            AuthIdentity(provider=AuthProvider.telegram, provider_user_id=str(telegram_id))
        )
        session.add(user)
        await session.commit()
        user.telegram_test_id = telegram_id
        yield user
        await session.execute(delete(Payment).where(Payment.user_id == user.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def add_lecture(user: User, storage: Path) -> tuple[Lecture, list[Path]]:
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title="Лекция", source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        files = [
            storage / "originals" / str(lecture.id),
            storage / "audio" / f"{lecture.id}.opus",
            storage / "videos" / f"{lecture.id}.mp4",
            storage / "uploads" / f"{user.id.hex}abcd",
            storage / "uploads" / f"{user.id.hex}abcd.info",
            storage / "tmp" / f"{lecture.id}.mp4",
            storage / "audio" / f"{lecture.id}.webm.part",
        ]
        for file in files:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"data")
        lecture.audio_path = str(files[1])
        lecture.video_path = str(files[2])
        await session.commit()
        return lecture, files


async def add_payment(user: User) -> uuid.UUID:
    async with SessionLocal() as session:
        payment = Payment(
            user_id=user.id,
            kind=PaymentKind.package,
            product_code="hours_10",
            amount_kopecks=100000,
            status=PaymentStatus.succeeded,
            idempotence_key=uuid.uuid4().hex,
            raw={"metadata": {"user_id": str(user.id)}},
        )
        session.add(payment)
        await session.commit()
        return payment.id


async def test_delete_with_password(client, account, storage):
    lecture, files = await add_lecture(account, storage)
    other = storage / "originals" / "someone-else"
    other.write_bytes(b"data")
    payment_id = await add_payment(account)
    token_headers = headers(account)

    response = await client.post(URL, json={"password": PASSWORD}, headers=token_headers)
    assert response.status_code == 204

    assert (await client.get("/api/v1/me", headers=token_headers)).status_code == 401
    assert not any(file.exists() for file in files)
    assert other.exists()
    async with SessionLocal() as session:
        assert await session.get(User, account.id) is None
        assert await session.get(Lecture, lecture.id) is None
        assert not (
            await session.scalars(select(AuthIdentity).where(AuthIdentity.user_id == account.id))
        ).all()
        payment = await session.get(Payment, payment_id)
        assert payment is not None
        assert payment.user_id is None
        assert payment.raw == {}
        assert payment.amount_kopecks == 100000
        await session.delete(payment)
        await session.commit()


async def test_wrong_password_keeps_everything(client, account, storage):
    _, files = await add_lecture(account, storage)

    response = await client.post(URL, json={"password": "не-тот-пароль"}, headers=headers(account))
    assert response.status_code == 403

    assert all(file.exists() for file in files)
    assert (await client.get("/api/v1/me", headers=headers(account))).status_code == 200


async def test_requires_confirmation(client, account):
    response = await client.post(URL, json={}, headers=headers(account))
    assert response.status_code == 422
    assert (await client.get("/api/v1/me", headers=headers(account))).status_code == 200


async def test_requires_auth(client):
    response = await client.post(URL, json={"password": PASSWORD})
    assert response.status_code == 401


async def test_delete_with_telegram_login(client, account, storage, bot_token):
    payload = signed(
        bot_token, id=account.telegram_test_id, first_name="Иван", auth_date=int(time.time())
    )
    response = await client.post(URL, json={"telegram": payload}, headers=headers(account))
    assert response.status_code == 204
    async with SessionLocal() as session:
        assert await session.get(User, account.id) is None


async def test_telegram_login_of_another_account_rejected(client, account, storage, bot_token):
    payload = signed(
        bot_token, id=account.telegram_test_id + 1, first_name="Иван", auth_date=int(time.time())
    )
    response = await client.post(URL, json={"telegram": payload}, headers=headers(account))
    assert response.status_code == 403
    assert (await client.get("/api/v1/me", headers=headers(account))).status_code == 200


async def test_delete_with_init_data(client, account, storage, bot_token):
    body = {"telegram_init_data": init_data(bot_token, **webapp_fields(account.telegram_test_id))}
    response = await client.post(URL, json=body, headers=headers(account))
    assert response.status_code == 204
    async with SessionLocal() as session:
        assert await session.get(User, account.id) is None


async def test_forged_init_data_rejected(client, account, bot_token):
    fields = webapp_fields(account.telegram_test_id, user=json.dumps({"id": 1}))
    body = {"telegram_init_data": init_data("654321:other-token", **fields)}
    response = await client.post(URL, json=body, headers=headers(account))
    assert response.status_code == 401
    assert (await client.get("/api/v1/me", headers=headers(account))).status_code == 200
