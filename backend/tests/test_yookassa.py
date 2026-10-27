import json
from collections.abc import Callable, Iterator

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.api.billing import get_yookassa_factory
from app.core.config import Settings
from app.core.db import SessionLocal
from app.main import app
from app.models import Payment, PaymentKind, PaymentStatus, User
from app.services import yookassa
from app.services.quota import list_products

SETTINGS = Settings(
    yookassa_shop_id="shop",
    yookassa_secret_key="secret",
    yookassa_api_url="https://yookassa.test/v3",
)
CONFIRMATION_URL = "https://yoomoney.ru/checkout/payments/v2/contract?orderId=1"


class FakeYooKassa:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.requests: list[httpx.Request] = []
        self.created: dict[str, str] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"type": "error"})
        key = request.headers["Idempotence-Key"]
        payment_id = self.created.setdefault(key, f"yk-{len(self.created) + 1}")
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": payment_id,
                "status": "pending",
                "amount": body["amount"],
                "confirmation": {"type": "redirect", "confirmation_url": CONFIRMATION_URL},
                "metadata": body["metadata"],
            },
        )

    def client(self, settings: Settings = SETTINGS) -> yookassa.YooKassaClient:
        return yookassa.YooKassaClient(settings, transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fake() -> Iterator[FakeYooKassa]:
    fake = FakeYooKassa()
    app.dependency_overrides[get_yookassa_factory] = lambda: fake.client
    yield fake
    app.dependency_overrides.pop(get_yookassa_factory, None)


async def count_payments(user: User) -> int:
    async with SessionLocal() as session:
        return await session.scalar(
            select(func.count()).select_from(Payment).where(Payment.user_id == user.id)
        )


def product(code: str):
    return next(p for p in list_products(SETTINGS) if p.code == code)


async def test_create_payment_returns_confirmation_url(client, user, auth_headers, fake):
    response = await client.post(
        "/api/v1/billing/payments",
        json={"product_code": "hours_5", "accept_offer": True},
        headers={**auth_headers, "Idempotence-Key": "key-create"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["kind"] == "package"
    assert data["product_code"] == "hours_5"
    assert data["amount_kopecks"] == 19900
    assert data["confirmation_url"] == CONFIRMATION_URL

    [request] = fake.requests
    assert str(request.url) == "https://yookassa.test/v3/payments"
    assert request.headers["Idempotence-Key"] == "key-create"
    assert request.headers["Authorization"].startswith("Basic ")
    body = json.loads(request.content)
    assert body["amount"] == {"value": "199.00", "currency": "RUB"}
    assert body["capture"] is True
    assert body["confirmation"] == {
        "type": "redirect",
        "return_url": "http://localhost/account",
    }
    assert body["metadata"] == {"payment_id": data["id"], "user_id": str(user.id)}
    assert "receipt" not in body

    async with SessionLocal() as session:
        payment = await session.get(Payment, data["id"])
        assert payment.status == PaymentStatus.pending
        assert payment.yookassa_id == "yk-1"
        assert payment.idempotence_key == "key-create"


async def test_same_key_does_not_create_second_payment(client, user, auth_headers, fake):
    request = {"product_code": "subscription", "accept_offer": True}
    headers = {**auth_headers, "Idempotence-Key": "key-repeat"}

    first = await client.post("/api/v1/billing/payments", json=request, headers=headers)
    second = await client.post("/api/v1/billing/payments", json=request, headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(fake.requests) == 1
    assert await count_payments(user) == 1


async def test_same_key_for_other_product_is_conflict(client, user, auth_headers, fake):
    headers = {**auth_headers, "Idempotence-Key": "key-conflict"}
    await client.post(
        "/api/v1/billing/payments",
        json={"product_code": "hours_5", "accept_offer": True},
        headers=headers,
    )

    response = await client.post(
        "/api/v1/billing/payments",
        json={"product_code": "hours_10", "accept_offer": True},
        headers=headers,
    )

    assert response.status_code == 409
    assert await count_payments(user) == 1


async def test_payment_requires_offer_acceptance(client, user, auth_headers, fake):
    response = await client.post(
        "/api/v1/billing/payments",
        json={"product_code": "hours_5", "accept_offer": False},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert fake.requests == []
    assert await count_payments(user) == 0


async def test_payment_without_accept_offer_field_is_rejected(client, auth_headers, fake):
    response = await client.post(
        "/api/v1/billing/payments", json={"product_code": "hours_5"}, headers=auth_headers
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"product_code": "hours_100", "accept_offer": True},
        {"product_code": "hours_5", "accept_offer": True, "return_url": "https://evil.test/pay"},
    ],
)
async def test_invalid_payment_request(client, user, auth_headers, fake, payload):
    response = await client.post("/api/v1/billing/payments", json=payload, headers=auth_headers)

    assert response.status_code == 422
    assert fake.requests == []


async def test_retry_after_yookassa_error_reuses_payment(client, user, auth_headers, fake):
    request = {"product_code": "hours_5", "accept_offer": True}
    headers = {**auth_headers, "Idempotence-Key": "key-retry"}
    fake.status_code = 500

    failed = await client.post("/api/v1/billing/payments", json=request, headers=headers)
    history = await client.get("/api/v1/billing/payments", headers=auth_headers)
    fake.status_code = 200
    retried = await client.post("/api/v1/billing/payments", json=request, headers=headers)

    assert failed.status_code == 502
    assert history.json() == []
    assert retried.status_code == 200
    assert await count_payments(user) == 1
    first_body, retry_body = (json.loads(r.content) for r in fake.requests)
    assert first_body["metadata"]["payment_id"] == retry_body["metadata"]["payment_id"]
    assert retry_body["metadata"]["payment_id"] == retried.json()["id"]


async def test_yookassa_rejection_does_not_keep_payment(client, user, auth_headers, fake):
    fake.status_code = 400

    response = await client.post(
        "/api/v1/billing/payments",
        json={"product_code": "hours_5", "accept_offer": True},
        headers=auth_headers,
    )

    assert response.status_code == 502
    assert await count_payments(user) == 0


async def test_payment_unavailable_without_credentials(client, auth_headers):
    def factory() -> Callable[[], yookassa.YooKassaClient]:
        return lambda: yookassa.YooKassaClient(Settings(yookassa_shop_id=""))

    app.dependency_overrides[get_yookassa_factory] = factory
    try:
        response = await client.post(
            "/api/v1/billing/payments",
            json={"product_code": "hours_5", "accept_offer": True},
            headers=auth_headers,
        )
    finally:
        app.dependency_overrides.pop(get_yookassa_factory, None)

    assert response.status_code == 503


async def test_list_payments_returns_only_own(client, user, auth_headers, fake):
    for key, code in (("key-list-1", "hours_5"), ("key-list-2", "subscription")):
        await client.post(
            "/api/v1/billing/payments",
            json={"product_code": code, "accept_offer": True},
            headers={**auth_headers, "Idempotence-Key": key},
        )
    async with SessionLocal() as session:
        other = User(display_name="Другой")
        session.add(other)
        await session.flush()
        session.add(
            Payment(
                user_id=other.id,
                kind=PaymentKind.package,
                product_code="hours_5",
                amount_kopecks=19900,
                idempotence_key="key-list-other",
                yookassa_id="yk-other",
            )
        )
        await session.commit()

    try:
        response = await client.get("/api/v1/billing/payments", headers=auth_headers)
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, other.id))
            await session.execute(delete(Payment).where(Payment.yookassa_id == "yk-other"))
            await session.commit()

    assert response.status_code == 200
    data = response.json()
    assert [p["product_code"] for p in data] == ["subscription", "hours_5"]
    assert all(p["confirmation_url"] == CONFIRMATION_URL for p in data)


async def test_list_payments_requires_auth(client):
    response = await client.get("/api/v1/billing/payments")

    assert response.status_code == 401


async def test_receipt_is_sent_with_email(user):
    settings = SETTINGS.model_copy(update={"yookassa_receipt": True})
    fake = FakeYooKassa()
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        db_user.email = f"{user.id}@lecturo.test"
        await session.commit()
        payment = await yookassa.create_payment(
            session,
            fake.client(settings),
            db_user,
            product("hours_10"),
            "key-receipt",
            "http://localhost/account",
            settings,
        )

    body = json.loads(fake.requests[0].content)
    assert payment.amount_kopecks == 34900
    assert body["receipt"]["customer"] == {"email": f"{user.id}@lecturo.test"}
    [item] = body["receipt"]["items"]
    assert item["amount"] == {"value": "349.00", "currency": "RUB"}
    assert item["quantity"] == "1.00"
    assert item["description"] == "Пакет 10 ч"


async def test_receipt_requires_email(user):
    settings = SETTINGS.model_copy(update={"yookassa_receipt": True})
    fake = FakeYooKassa()
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        with pytest.raises(yookassa.PaymentError, match="email"):
            await yookassa.create_payment(
                session,
                fake.client(settings),
                db_user,
                product("hours_5"),
                "key-receipt-no-email",
                "http://localhost/account",
                settings,
            )

    assert fake.requests == []
    assert await count_payments(user) == 0


def test_client_requires_credentials():
    with pytest.raises(ValueError, match="YOOKASSA_SHOP_ID"):
        yookassa.YooKassaClient(Settings(yookassa_shop_id="", yookassa_secret_key="secret"))


def test_format_amount():
    assert yookassa.format_amount(29900) == {"value": "299.00", "currency": "RUB"}
    assert yookassa.format_amount(12345) == {"value": "123.45", "currency": "RUB"}
