import random
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.api.billing import get_yookassa_factory
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.main import app
from app.models import (
    AdminAuditEntry,
    AlertDelivery,
    AlertKind,
    AlertSignal,
    AuthIdentity,
    AuthProvider,
    User,
)
from app.services.admin_alerts import TEST_ALERT
from tests.test_yookassa_webhook import WEBHOOK, FakeYooKassa, make_payment, notification


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}


async def create_admin(telegram_started: bool | None) -> User:
    async with SessionLocal() as session:
        user = User(
            email=f"alerts-{uuid.uuid4().hex[:10]}@example.org",
            display_name="Админ",
            is_admin=True,
        )
        if telegram_started is not None:
            user.identities.append(
                AuthIdentity(
                    provider=AuthProvider.telegram,
                    provider_user_id=str(random.randint(10**9, 10**10)),
                    bot_started_at=datetime.now(UTC) if telegram_started else None,
                )
            )
        session.add(user)
        await session.commit()
        return user


async def drop_users(*users: User) -> None:
    ids = [user.id for user in users]
    async with SessionLocal() as session:
        await session.execute(delete(AdminAuditEntry).where(AdminAuditEntry.actor_id.in_(ids)))
        await session.execute(delete(User).where(User.id.in_(ids)))
        await session.commit()


@pytest.fixture
async def admin() -> AsyncIterator[User]:
    user = await create_admin(telegram_started=None)
    yield user
    await drop_users(user)


@pytest.fixture
async def ready_admin() -> AsyncIterator[User]:
    user = await create_admin(telegram_started=True)
    yield user
    await drop_users(user)


@pytest.fixture
def fake() -> Iterator[FakeYooKassa]:
    fake = FakeYooKassa()
    app.dependency_overrides[get_yookassa_factory] = lambda: fake.client
    yield fake
    app.dependency_overrides.pop(get_yookassa_factory, None)


async def signals_for(key: str) -> list[AlertSignal]:
    async with SessionLocal() as session:
        rows = await session.scalars(select(AlertSignal).where(AlertSignal.key.contains(key)))
        found = list(rows)
        await session.execute(delete(AlertSignal).where(AlertSignal.key.contains(key)))
        await session.commit()
        return found


async def test_defaults_enable_every_kind(client, admin):
    response = await client.get("/api/v1/admin/alerts/settings", headers=headers(admin))

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "kinds": [kind.value for kind in AlertKind],
        "recoveries": True,
        "telegram": "not_linked",
    }


async def test_regular_user_has_no_access(client, user, auth_headers):
    for method, path in [
        ("GET", "/api/v1/admin/alerts/settings"),
        ("PUT", "/api/v1/admin/alerts/settings"),
        ("POST", "/api/v1/admin/alerts/test"),
    ]:
        response = await client.request(method, path, headers=auth_headers, json={})
        assert response.status_code == 404, (method, path)


async def test_saved_settings_are_returned_and_audited(client, admin):
    body = {"enabled": False, "kinds": ["payment", "disk_low"], "recoveries": False}

    saved = await client.put("/api/v1/admin/alerts/settings", headers=headers(admin), json=body)
    again = await client.get("/api/v1/admin/alerts/settings", headers=headers(admin))

    assert saved.status_code == 200
    assert again.json() == {
        "enabled": False,
        "kinds": ["disk_low", "payment"],
        "recoveries": False,
        "telegram": "not_linked",
    }
    async with SessionLocal() as session:
        [entry] = await session.scalars(
            select(AdminAuditEntry).where(AdminAuditEntry.actor_id == admin.id)
        )
    assert entry.action == "alert_settings_changed"
    assert entry.details["source"] == "panel"
    assert entry.details["kinds"] == ["disk_low", "payment"]


async def test_unknown_kind_is_rejected(client, admin):
    body = {"enabled": True, "kinds": ["weather"], "recoveries": True}

    response = await client.put("/api/v1/admin/alerts/settings", headers=headers(admin), json=body)

    assert response.status_code == 422


async def test_test_alert_needs_started_bot(client, admin):
    response = await client.post("/api/v1/admin/alerts/test", headers=headers(admin))

    assert response.status_code == 409
    async with SessionLocal() as session:
        queued = await session.scalars(
            select(AlertDelivery).where(AlertDelivery.user_id == admin.id)
        )
        assert list(queued) == []


async def test_test_alert_is_queued_for_admin(client, ready_admin):
    response = await client.post("/api/v1/admin/alerts/test", headers=headers(ready_admin))

    assert response.status_code == 202
    async with SessionLocal() as session:
        [delivery] = await session.scalars(
            select(AlertDelivery).where(AlertDelivery.user_id == ready_admin.id)
        )
    assert delivery.text == TEST_ALERT
    assert delivery.sent_at is None


async def test_succeeded_payment_raises_payment_signal(client, user, fake):
    payment = await make_payment(user, "hours_5")
    fake.set_remote(payment, "succeeded")

    await client.post(WEBHOOK, json=notification(payment))
    await client.post(WEBHOOK, json=notification(payment))

    [signal] = await signals_for(str(payment.id))
    assert signal.kind == AlertKind.payment
    assert signal.state == "event"
    assert signal.dispatched_at is None
    assert "199 ₽" in signal.text


async def test_rejected_webhook_raises_webhook_signal(client, user, fake):
    payment = await make_payment(user, "hours_5")

    response = await client.post(WEBHOOK, json=notification(payment))

    [signal] = await signals_for(payment.yookassa_id)
    assert response.status_code == 400
    assert signal.kind == AlertKind.webhook_error
    assert payment.yookassa_id in signal.text
