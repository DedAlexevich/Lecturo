import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.api.billing import get_yookassa_factory
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.main import app
from app.models import (
    HourPackage,
    Lecture,
    Payment,
    PaymentKind,
    PaymentStatus,
    SourceType,
    Subscription,
    UsageEntry,
    UsageSource,
    User,
)
from app.services import quota, yookassa

SETTINGS = Settings(
    yookassa_shop_id="shop",
    yookassa_secret_key="secret",
    yookassa_api_url="https://yookassa.test/v3",
)
WEBHOOK = "/api/v1/billing/webhook"


class FakeYooKassa:
    def __init__(self) -> None:
        self.payments: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        self.status_code = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"type": "error"})
        yookassa_id = request.url.path.removeprefix("/v3/payments/")
        if request.method != "GET" or yookassa_id not in self.payments:
            return httpx.Response(404, json={"type": "error", "code": "not_found"})
        return httpx.Response(200, json=self.payments[yookassa_id])

    def client(self) -> yookassa.YooKassaClient:
        return yookassa.YooKassaClient(SETTINGS, transport=httpx.MockTransport(self.handler))

    def set_remote(
        self, payment: Payment, status: str, value: str | None = None, **extra: Any
    ) -> None:
        amount = value or yookassa.format_amount(payment.amount_kopecks)["value"]
        self.payments[payment.yookassa_id] = {
            "id": payment.yookassa_id,
            "status": status,
            "paid": status == "succeeded",
            "amount": {"value": amount, "currency": "RUB"},
            "metadata": {"payment_id": str(payment.id), "user_id": str(payment.user_id)},
            **extra,
        }


@pytest.fixture
def fake() -> Iterator[FakeYooKassa]:
    fake = FakeYooKassa()
    app.dependency_overrides[get_yookassa_factory] = lambda: fake.client
    yield fake
    app.dependency_overrides.pop(get_yookassa_factory, None)


async def make_payment(user: User, product_code: str = "hours_5") -> Payment:
    kind = PaymentKind.subscription if product_code == "subscription" else PaymentKind.package
    amounts = {"subscription": 29900, "hours_5": 19900, "hours_10": 34900}
    async with SessionLocal() as session:
        payment = Payment(
            user_id=user.id,
            kind=kind,
            product_code=product_code,
            amount_kopecks=amounts[product_code],
            idempotence_key=str(uuid.uuid4()),
            yookassa_id=f"yk-{uuid.uuid4()}",
            raw={},
        )
        session.add(payment)
        await session.commit()
        return payment


def notification(payment: Payment, event: str = "payment.succeeded") -> dict[str, Any]:
    return {
        "type": "notification",
        "event": event,
        "object": {
            "id": payment.yookassa_id,
            "status": event.removeprefix("payment."),
            "paid": True,
            "amount": {"value": "100000.00", "currency": "RUB"},
            "metadata": {"payment_id": str(payment.id)},
        },
    }


async def load_payment(payment: Payment) -> Payment:
    async with SessionLocal() as session:
        return await session.get(Payment, payment.id)


async def packages_of(user: User) -> list[HourPackage]:
    async with SessionLocal() as session:
        result = await session.scalars(select(HourPackage).where(HourPackage.user_id == user.id))
        return list(result.all())


async def subscriptions_of(user: User) -> list[Subscription]:
    async with SessionLocal() as session:
        result = await session.scalars(
            select(Subscription)
            .where(Subscription.user_id == user.id)
            .order_by(Subscription.starts_at)
        )
        return list(result.all())


async def test_succeeded_package_increases_quota(client, user, auth_headers, fake):
    payment = await make_payment(user, "hours_5")
    fake.set_remote(
        payment,
        "succeeded",
        captured_at="2026-10-26T10:00:00.000Z",
        payment_method={"type": "bank_card", "card": {"first6": "555555", "last4": "4444"}},
    )
    fake.payments[payment.yookassa_id]["metadata"]["receipt_email"] = "buyer@example.org"

    response = await client.post(WEBHOOK, json=notification(payment))

    assert response.status_code == 200
    [request] = fake.requests
    assert request.method == "GET"
    assert str(request.url) == f"https://yookassa.test/v3/payments/{payment.yookassa_id}"
    assert request.headers["Authorization"].startswith("Basic ")
    stored = await load_payment(payment)
    assert stored.status == PaymentStatus.succeeded
    assert stored.paid_at == datetime(2026, 10, 26, 10, tzinfo=UTC)
    assert stored.raw == {
        "id": payment.yookassa_id,
        "status": "succeeded",
        "amount": {"value": "199.00", "currency": "RUB"},
        "captured_at": "2026-10-26T10:00:00.000Z",
    }
    [package] = await packages_of(user)
    assert package.payment_id == payment.id
    assert package.seconds_total == package.seconds_left == 5 * 3600
    quota = await client.get("/api/v1/billing/quota", headers=auth_headers)
    assert quota.json()["package_left_sec"] == 5 * 3600


async def test_repeated_notification_does_not_grant_twice(client, user, fake):
    payment = await make_payment(user, "hours_10")
    fake.set_remote(payment, "succeeded")

    first = await client.post(WEBHOOK, json=notification(payment))
    second = await client.post(WEBHOOK, json=notification(payment))

    assert first.status_code == second.status_code == 200
    assert len(fake.requests) == 1
    [package] = await packages_of(user)
    assert package.seconds_total == 10 * 3600


async def test_notification_for_payment_missing_in_db_skips_yookassa(client, user, fake):
    payment = await make_payment(user, "hours_5")
    body = notification(payment)
    body["object"]["id"] = f"yk-{uuid.uuid4()}"

    response = await client.post(WEBHOOK, json=body)

    assert response.status_code == 200
    assert fake.requests == []
    assert await packages_of(user) == []


async def test_webhook_unavailable_without_credentials(client, user):
    payment = await make_payment(user, "hours_5")
    app.dependency_overrides[get_yookassa_factory] = lambda: (
        lambda: yookassa.YooKassaClient(Settings(yookassa_shop_id=""))
    )
    try:
        response = await client.post(WEBHOOK, json=notification(payment))
    finally:
        app.dependency_overrides.pop(get_yookassa_factory, None)

    assert response.status_code == 503
    assert (await load_payment(payment)).status == PaymentStatus.pending


async def test_forged_notification_grants_nothing(client, user, fake):
    payment = await make_payment(user, "hours_5")
    fake.set_remote(payment, "pending")

    response = await client.post(WEBHOOK, json=notification(payment))

    assert response.status_code == 200
    assert (await load_payment(payment)).status == PaymentStatus.pending
    assert await packages_of(user) == []


async def test_notification_for_payment_missing_in_yookassa_is_rejected(client, user, fake):
    payment = await make_payment(user, "hours_5")

    response = await client.post(WEBHOOK, json=notification(payment))

    assert response.status_code == 400
    assert (await load_payment(payment)).status == PaymentStatus.pending
    assert await packages_of(user) == []


async def test_payment_bound_to_other_record_grants_nothing(client, user, fake):
    payment = await make_payment(user, "hours_5")
    fake.set_remote(payment, "succeeded")
    fake.payments[payment.yookassa_id]["metadata"]["payment_id"] = str(uuid.uuid4())

    response = await client.post(WEBHOOK, json=notification(payment))

    assert response.status_code == 200
    assert (await load_payment(payment)).status == PaymentStatus.pending
    assert await packages_of(user) == []


async def test_amount_mismatch_grants_nothing(client, user, fake):
    payment = await make_payment(user, "hours_10")
    fake.set_remote(payment, "succeeded", value="1.00")

    first = await client.post(WEBHOOK, json=notification(payment))
    second = await client.post(WEBHOOK, json=notification(payment))

    assert first.status_code == second.status_code == 200
    assert len(fake.requests) == 1
    assert (await load_payment(payment)).status == PaymentStatus.canceled
    assert await packages_of(user) == []


async def test_canceled_payment_changes_status(client, user, fake):
    payment = await make_payment(user, "subscription")
    fake.set_remote(payment, "canceled")

    response = await client.post(WEBHOOK, json=notification(payment, "payment.canceled"))

    assert response.status_code == 200
    assert (await load_payment(payment)).status == PaymentStatus.canceled
    assert await subscriptions_of(user) == []


async def test_subscription_starts_now_and_raises_weekly_limit(client, user, auth_headers, fake):
    payment = await make_payment(user, "subscription")
    fake.set_remote(payment, "succeeded")
    before = datetime.now(UTC)

    response = await client.post(WEBHOOK, json=notification(payment))

    assert response.status_code == 200
    [subscription] = await subscriptions_of(user)
    assert subscription.payment_id == payment.id
    assert before <= subscription.starts_at <= datetime.now(UTC)
    assert subscription.ends_at - subscription.starts_at == timedelta(days=30)
    quota = (await client.get("/api/v1/billing/quota", headers=auth_headers)).json()
    assert quota["weekly_limit_sec"] == get_settings().subscription_weekly_seconds
    assert quota["subscription_until"] is not None


async def test_subscription_extends_uploaded_video_retention(client, user, fake):
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Лекция",
            source_type=SourceType.upload,
            video_path="/tmp/lecture.mp4",
            video_expires_at=datetime.now(UTC) + timedelta(days=3),
        )
        session.add(lecture)
        await session.commit()
    payment = await make_payment(user, "subscription")
    fake.set_remote(payment, "succeeded")

    before = datetime.now(UTC)

    response = await client.post(WEBHOOK, json=notification(payment))

    assert response.status_code == 200
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, lecture.id)
    days = timedelta(days=get_settings().subscription_video_retention_days)
    assert before + days <= lecture.video_expires_at <= datetime.now(UTC) + days


async def test_subscription_extends_active_one(client, user, auth_headers, fake):
    current_end = datetime.now(UTC) + timedelta(days=5)
    async with SessionLocal() as session:
        session.add(
            Subscription(
                user_id=user.id,
                starts_at=current_end - timedelta(days=30),
                ends_at=current_end,
            )
        )
        await session.commit()
    first = await make_payment(user, "subscription")
    second = await make_payment(user, "subscription")
    fake.set_remote(first, "succeeded")
    fake.set_remote(second, "succeeded")

    await client.post(WEBHOOK, json=notification(first))
    await client.post(WEBHOOK, json=notification(second))

    _, extended, next_one = await subscriptions_of(user)
    assert extended.payment_id == first.id
    assert extended.starts_at == current_end
    assert extended.ends_at == current_end + timedelta(days=30)
    assert next_one.payment_id == second.id
    assert next_one.starts_at == extended.ends_at
    quota = (await client.get("/api/v1/billing/quota", headers=auth_headers)).json()
    assert datetime.fromisoformat(quota["subscription_until"]) == next_one.ends_at


async def test_yookassa_unavailable_asks_for_retry(client, user, fake):
    payment = await make_payment(user, "hours_5")
    fake.set_remote(payment, "succeeded")
    fake.status_code = 500

    response = await client.post(WEBHOOK, json=notification(payment))

    assert response.status_code == 502
    assert (await load_payment(payment)).status == PaymentStatus.pending


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"event": "payment.succeeded", "object": "yk-1"},
        {"event": "payment.succeeded", "object": {"id": "../refunds"}},
    ],
)
async def test_malformed_notification_is_rejected(client, fake, body):
    response = await client.post(WEBHOOK, json=body)

    assert response.status_code == 400
    assert fake.requests == []


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ({"value": "299.00", "currency": "RUB"}, 29900),
        ({"value": "349.5", "currency": "RUB"}, 34950),
        ({"value": "1.001", "currency": "RUB"}, None),
        ({"value": "299.00", "currency": "USD"}, None),
        ({"value": "abc", "currency": "RUB"}, None),
        ({"value": "Infinity", "currency": "RUB"}, None),
        ({"value": "NaN", "currency": "RUB"}, None),
        (None, None),
    ],
)
def test_parse_amount(amount, expected):
    assert yookassa.parse_amount(amount) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-26T10:00:00.000Z", datetime(2026, 10, 26, 10, tzinfo=UTC)),
        ("2026-10-26T10:00:00", datetime(2026, 10, 26, 10, tzinfo=UTC)),
        ("2026-10-26T13:00:00+03:00", datetime(2026, 10, 26, 10, tzinfo=UTC)),
        ("вчера", None),
        (None, None),
    ],
)
def test_parse_time(value, expected):
    assert yookassa.parse_time(value) == expected


async def test_payment_of_deleted_account_is_settled_without_grant(client, user, fake):
    payment = await make_payment(user, "hours_5")
    fake.set_remote(payment, "succeeded", captured_at="2026-10-26T10:00:00.000Z")
    async with SessionLocal() as session:
        stored = await session.get(Payment, payment.id)
        stored.user_id = None
        await session.commit()

    response = await client.post(WEBHOOK, json=notification(payment))

    assert response.status_code == 200
    stored = await load_payment(payment)
    assert stored.status == PaymentStatus.succeeded
    assert stored.paid_at == datetime(2026, 10, 26, 10, tzinfo=UTC)
    assert await packages_of(user) == []
    async with SessionLocal() as session:
        await session.delete(stored)
        await session.commit()


def refund_notification(payment: Payment) -> dict[str, Any]:
    return {
        "type": "notification",
        "event": "refund.succeeded",
        "object": {
            "id": f"rf-{uuid.uuid4()}",
            "payment_id": payment.yookassa_id,
            "status": "succeeded",
            "amount": yookassa.format_amount(payment.amount_kopecks),
        },
    }


def refund_remote(fake: FakeYooKassa, payment: Payment, kopecks: int | None = None) -> None:
    refunded = yookassa.format_amount(payment.amount_kopecks if kopecks is None else kopecks)
    fake.payments[payment.yookassa_id]["refunded_amount"] = refunded


async def test_refund_revokes_package(client, user, auth_headers, fake):
    payment = await make_payment(user, "hours_5")
    fake.set_remote(payment, "succeeded")
    await client.post(WEBHOOK, json=notification(payment))
    refund_remote(fake, payment)

    requests_before = len(fake.requests)
    first = await client.post(WEBHOOK, json=refund_notification(payment))
    second = await client.post(WEBHOOK, json=refund_notification(payment))

    assert first.status_code == second.status_code == 200
    assert len(fake.requests) == requests_before + 1
    assert str(fake.requests[-1].url) == f"https://yookassa.test/v3/payments/{payment.yookassa_id}"
    [package] = await packages_of(user)
    assert package.seconds_left == 0
    quota = await client.get("/api/v1/billing/quota", headers=auth_headers)
    assert quota.json()["package_left_sec"] == 0
    stored = await load_payment(payment)
    assert stored.raw["refunded_amount"] == {"value": "199.00", "currency": "RUB"}
    assert stored.status == PaymentStatus.refunded
    history = await client.get("/api/v1/billing/payments", headers=auth_headers)
    assert [item["status"] for item in history.json()] == ["refunded"]


async def test_refund_then_lecture_cancel_keeps_package_empty(client, user, fake):
    payment = await make_payment(user, "hours_5")
    fake.set_remote(payment, "succeeded")
    await client.post(WEBHOOK, json=notification(payment))
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title="Лекция", source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        db_user = await session.get(User, user.id)
        db_user.quota_week_start = datetime.now(UTC)
        session.add(
            UsageEntry(
                user_id=user.id,
                lecture_id=lecture.id,
                source=UsageSource.package,
                package_id=(await packages_of(user))[0].id,
                seconds=600,
            )
        )
        await session.commit()
        lecture_id = lecture.id
    refund_remote(fake, payment)
    await client.post(WEBHOOK, json=refund_notification(payment))

    async with SessionLocal() as session:
        await quota.refund_lecture(session, lecture_id)
        await session.commit()

    [package] = await packages_of(user)
    assert package.seconds_left == 0


async def test_refund_shortens_subscription_and_moves_next_one(client, user, auth_headers, fake):
    first = await make_payment(user, "subscription")
    second = await make_payment(user, "subscription")
    fake.set_remote(first, "succeeded")
    fake.set_remote(second, "succeeded")
    await client.post(WEBHOOK, json=notification(first))
    await client.post(WEBHOOK, json=notification(second))
    refund_remote(fake, first)

    before = datetime.now(UTC)
    response = await client.post(WEBHOOK, json=refund_notification(first))
    await client.post(WEBHOOK, json=refund_notification(first))

    assert response.status_code == 200
    refunded, next_one = await subscriptions_of(user)
    assert refunded.payment_id == first.id
    assert before <= refunded.ends_at <= datetime.now(UTC)
    assert next_one.starts_at == refunded.ends_at
    assert next_one.ends_at - next_one.starts_at == timedelta(days=30)
    quota = (await client.get("/api/v1/billing/quota", headers=auth_headers)).json()
    assert datetime.fromisoformat(quota["subscription_until"]) == next_one.ends_at


async def test_partial_refund_keeps_package(client, user, fake):
    payment = await make_payment(user, "hours_5")
    fake.set_remote(payment, "succeeded")
    await client.post(WEBHOOK, json=notification(payment))
    refund_remote(fake, payment, 5000)

    response = await client.post(WEBHOOK, json=refund_notification(payment))

    assert response.status_code == 200
    [package] = await packages_of(user)
    assert package.seconds_left == 5 * 3600


async def test_refund_of_unpaid_payment_skips_yookassa(client, user, fake):
    payment = await make_payment(user, "hours_5")

    response = await client.post(WEBHOOK, json=refund_notification(payment))

    assert response.status_code == 200
    assert fake.requests == []
