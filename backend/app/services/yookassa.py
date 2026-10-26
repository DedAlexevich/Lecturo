import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import (
    HourPackage,
    Payment,
    PaymentKind,
    PaymentStatus,
    Subscription,
    User,
)
from app.schemas.billing import PaymentOut, ProductOut
from app.services.quota import list_products

YOOKASSA_ID = re.compile(r"[\w-]{1,64}")
logger = logging.getLogger(__name__)


class YooKassaError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    @property
    def rejected(self) -> bool:
        return (
            self.status_code is not None
            and 400 <= self.status_code < 500
            and (self.status_code != 429)
        )


class PaymentError(ValueError):
    pass


class IdempotenceKeyConflict(PaymentError):
    pass


class NotificationError(ValueError):
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

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=30, auth=self.auth, transport=self.transport
        ) as client:
            try:
                response = await client.request(method, f"{self.api_url}{path}", **kwargs)
            except httpx.HTTPError as error:
                raise YooKassaError(f"ЮKassa недоступна: {error}") from error
        if response.is_error:
            raise YooKassaError(
                f"ЮKassa вернула {response.status_code}: {response.text[:500]}",
                response.status_code,
            )
        return response.json()

    async def create_payment(self, idempotence_key: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self.request(
            "POST", "/payments", json=body, headers={"Idempotence-Key": idempotence_key}
        )

    async def get_payment(self, yookassa_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/payments/{yookassa_id}")


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
    return ((payment.raw or {}).get("confirmation") or {}).get("confirmation_url")


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


async def find_by_key(
    session: AsyncSession, user_id: uuid.UUID, idempotence_key: str
) -> Payment | None:
    return await session.scalar(
        select(Payment).where(
            Payment.user_id == user_id, Payment.idempotence_key == idempotence_key
        )
    )


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
    payment = await find_by_key(session, user_id, idempotence_key)
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
            payment = await find_by_key(session, user_id, idempotence_key)
            if payment is None:
                raise IdempotenceKeyConflict("Платёж с этим ключом ещё создаётся") from None
    if payment.product_code != product.code:
        raise IdempotenceKeyConflict("Ключ идемпотентности уже использован для другого платежа")
    if payment.yookassa_id:
        return payment

    body = payment_request(payment, product, email, return_url, settings)
    try:
        response = await client.create_payment(idempotence_key, body)
    except YooKassaError as error:
        if error.rejected:
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


def notification_payment_id(body: dict[str, Any]) -> str:
    payment_object = body.get("object")
    yookassa_id = payment_object.get("id") if isinstance(payment_object, dict) else None
    if not isinstance(yookassa_id, str) or not YOOKASSA_ID.fullmatch(yookassa_id):
        raise NotificationError("В уведомлении нет id платежа")
    return yookassa_id


def parse_amount(amount: Any) -> int | None:
    if not isinstance(amount, dict) or amount.get("currency") != "RUB":
        return None
    try:
        kopecks = Decimal(str(amount.get("value"))) * 100
    except InvalidOperation:
        return None
    return int(kopecks) if kopecks == kopecks.to_integral_value() else None


def parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


async def grant_subscription(
    session: AsyncSession, payment: Payment, now: datetime, settings: Settings
) -> Subscription:
    await session.get(User, payment.user_id, with_for_update=True)
    current_end = await session.scalar(
        select(func.max(Subscription.ends_at)).where(
            Subscription.user_id == payment.user_id, Subscription.ends_at > now
        )
    )
    starts_at = current_end or now
    subscription = Subscription(
        user_id=payment.user_id,
        payment_id=payment.id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(days=settings.subscription_days),
    )
    session.add(subscription)
    return subscription


def grant_package(session: AsyncSession, payment: Payment, settings: Settings) -> HourPackage:
    product = next(
        (p for p in list_products(settings) if p.code == payment.product_code and p.seconds),
        None,
    )
    if product is None:
        raise PaymentError(f"Нет пакета часов {payment.product_code}")
    package = HourPackage(
        user_id=payment.user_id,
        payment_id=payment.id,
        seconds_total=product.seconds,
        seconds_left=product.seconds,
    )
    session.add(package)
    return package


async def apply_succeeded(
    session: AsyncSession,
    payment: Payment,
    remote: dict[str, Any],
    now: datetime,
    settings: Settings,
) -> None:
    if parse_amount(remote.get("amount")) != payment.amount_kopecks:
        raise PaymentError(f"Сумма платежа {payment.id} не совпадает с ЮKassa")
    if payment.kind == PaymentKind.subscription:
        await grant_subscription(session, payment, now, settings)
    else:
        grant_package(session, payment, settings)
    payment.status = PaymentStatus.succeeded
    payment.paid_at = parse_time(remote.get("captured_at")) or now
    payment.raw = remote


async def has_pending_payment(session: AsyncSession, yookassa_id: str) -> bool:
    return await session.scalar(
        select(
            exists().where(
                Payment.yookassa_id == yookassa_id, Payment.status == PaymentStatus.pending
            )
        )
    )


async def process_notification(
    session: AsyncSession,
    client: YooKassaClient,
    yookassa_id: str,
    settings: Settings,
    now: datetime | None = None,
) -> Payment | None:
    remote = await client.get_payment(yookassa_id)
    if remote.get("id") != yookassa_id:
        raise NotificationError("ЮKassa вернула другой платёж")
    payment = await session.scalar(
        select(Payment).where(Payment.yookassa_id == yookassa_id).with_for_update()
    )
    if payment is None:
        logger.warning("Уведомление о неизвестном платеже %s", yookassa_id)
        return None
    if (remote.get("metadata") or {}).get("payment_id") != str(payment.id):
        logger.warning("Платёж %s в ЮKassa привязан к другой записи", yookassa_id)
        return None
    if payment.status != PaymentStatus.pending:
        return payment

    status = remote.get("status")
    if status == PaymentStatus.succeeded:
        await apply_succeeded(session, payment, remote, now or datetime.now(UTC), settings)
    elif status == PaymentStatus.canceled:
        payment.status = PaymentStatus.canceled
        payment.raw = remote
    await session.commit()
    return payment
