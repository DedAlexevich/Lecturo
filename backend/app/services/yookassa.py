import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Payment, User
from app.schemas.billing import PaymentOut, ProductOut


class YooKassaError(RuntimeError):
    pass


class PaymentError(ValueError):
    pass


class IdempotenceKeyConflict(PaymentError):
    pass


class YooKassaClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        required = {
            "YOOKASSA_SHOP_ID": settings.yookassa_shop_id,
            "YOOKASSA_SECRET_KEY": settings.yookassa_secret_key,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Не заданы настройки ЮKassa: {', '.join(missing)}")
        self.api_url = settings.yookassa_api_url.rstrip("/")
        self.auth = (settings.yookassa_shop_id, settings.yookassa_secret_key)
        self.transport = transport

    async def create_payment(self, idempotence_key: str, body: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=30, auth=self.auth, transport=self.transport
        ) as client:
            try:
                response = await client.post(
                    f"{self.api_url}/payments",
                    json=body,
                    headers={"Idempotence-Key": idempotence_key},
                )
            except httpx.HTTPError as error:
                raise YooKassaError(f"ЮKassa недоступна: {error}") from error
        if response.is_error:
            raise YooKassaError(f"ЮKassa вернула {response.status_code}: {response.text[:500]}")
        return response.json()


def format_amount(kopecks: int) -> dict[str, str]:
    return {"value": f"{kopecks // 100}.{kopecks % 100:02d}", "currency": "RUB"}


def payment_request(
    payment: Payment,
    product: ProductOut,
    email: str | None,
    return_url: str,
    settings: Settings,
) -> dict[str, Any]:
    amount = format_amount(payment.amount_kopecks)
    body: dict[str, Any] = {
        "amount": amount,
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": product.title,
        "metadata": {"payment_id": str(payment.id), "user_id": str(payment.user_id)},
    }
    if settings.yookassa_receipt:
        body["receipt"] = {
            "customer": {"email": email},
            "items": [
                {
                    "description": product.title,
                    "quantity": "1.00",
                    "amount": amount,
                    "vat_code": 1,
                    "payment_mode": "full_payment",
                    "payment_subject": "service",
                }
            ],
        }
    return body


def confirmation_url(payment: Payment) -> str | None:
    return (payment.raw or {}).get("confirmation", {}).get("confirmation_url")


def payment_out(payment: Payment) -> PaymentOut:
    return PaymentOut(
        id=payment.id,
        kind=payment.kind,
        product_code=payment.product_code,
        amount_kopecks=payment.amount_kopecks,
        status=payment.status,
        confirmation_url=confirmation_url(payment),
        created_at=payment.created_at,
        paid_at=payment.paid_at,
    )


async def find_by_key(session: AsyncSession, idempotence_key: str) -> Payment | None:
    return await session.scalar(select(Payment).where(Payment.idempotence_key == idempotence_key))


async def create_payment(
    session: AsyncSession,
    client: YooKassaClient,
    user: User,
    product: ProductOut,
    idempotence_key: str,
    return_url: str,
    settings: Settings,
) -> Payment:
    user_id, email = user.id, user.email
    if settings.yookassa_receipt and not email:
        raise PaymentError("Для чека нужен email: укажите его в профиле")
    payment = await find_by_key(session, idempotence_key)
    if payment is None:
        payment = Payment(
            user_id=user_id,
            kind=product.kind,
            product_code=product.code,
            amount_kopecks=product.price_rub * 100,
            idempotence_key=idempotence_key,
            raw={},
        )
        session.add(payment)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            payment = await find_by_key(session, idempotence_key)
            if payment is None:
                raise IdempotenceKeyConflict("Платёж с этим ключом ещё создаётся") from None
    if payment.user_id != user_id or payment.product_code != product.code:
        raise IdempotenceKeyConflict("Ключ идемпотентности уже использован для другого платежа")
    if payment.yookassa_id:
        return payment

    body = payment_request(payment, product, email, return_url, settings)
    try:
        response = await client.create_payment(idempotence_key, body)
    except YooKassaError:
        await session.delete(payment)
        await session.commit()
        raise
    payment.yookassa_id = response["id"]
    payment.raw = response
    await session.commit()
    return payment


async def list_payments(session: AsyncSession, user_id: uuid.UUID) -> list[Payment]:
    result = await session.scalars(
        select(Payment)
        .where(Payment.user_id == user_id, Payment.yookassa_id.is_not(None))
        .order_by(Payment.created_at.desc(), Payment.id)
    )
    return list(result.all())
