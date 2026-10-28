import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import (
    HourPackage,
    Payment,
    PaymentKind,
    PaymentStatus,
    PromoRedemption,
    Subscription,
    User,
)
from app.pipeline.retention import extend_video_retention
from app.schemas.billing import PaymentOut, ProductOut
from app.services import promo
from app.services.admin_alerts import report_payment
from app.services.auth import normalize_email
from app.services.quota import list_products

YOOKASSA_ID = re.compile(r"[\w-]{1,64}")
REFUND_SUCCEEDED = "refund.succeeded"
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
    email: str,
    return_url: str,
    settings: Settings,
) -> dict[str, Any]:
    amount = format_amount(payment.amount_kopecks)
    body: dict[str, Any] = {
        "amount": amount,
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": product.title,
        "metadata": {
            "payment_id": str(payment.id),
            "user_id": str(payment.user_id),
            "receipt_email": email,
        },
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


def stored_raw(remote: dict[str, Any]) -> dict[str, Any]:
    fields = ("id", "status", "amount", "refunded_amount", "captured_at")
    raw = {key: remote[key] for key in fields if key in remote}
    url = (remote.get("confirmation") or {}).get("confirmation_url")
    if url:
        raw["confirmation"] = {"confirmation_url": url}
    return raw


def confirmation_url(payment: Payment) -> str | None:
    return ((payment.raw or {}).get("confirmation") or {}).get("confirmation_url")


def payment_out(payment: Payment) -> PaymentOut:
    return PaymentOut(
        id=payment.id,
        kind=payment.kind,
        product_code=payment.product_code,
        amount_kopecks=payment.amount_kopecks,
        discount_kopecks=payment.discount_kopecks,
        status=payment.status,
        confirmation_url=confirmation_url(payment),
        created_at=payment.created_at,
        paid_at=payment.paid_at,
    )


def yookassa_idempotence_key(user_id: uuid.UUID, idempotence_key: str) -> str:
    return hashlib.sha256(f"{user_id}:{idempotence_key}".encode()).hexdigest()[:64]


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
    receipt_email: str | None = None,
    promo_code: str | None = None,
) -> Payment:
    user_id = user.id
    email = user.email or (normalize_email(receipt_email) if receipt_email else None)
    if not email:
        raise PaymentError("Для чека нужен email: укажите адрес, на который отправить чек")
    code = promo.normalize_code(promo_code or "") or None
    payment = await find_by_key(session, user_id, idempotence_key)
    if payment is None:
        price = product.price_rub * 100
        reserved, discount = None, 0
        if code:
            reserved, discount = await promo.reserve_discount(
                session, user_id, code, price, datetime.now(UTC)
            )
        payment = Payment(
            user_id=user_id,
            kind=product.kind,
            product_code=product.code,
            amount_kopecks=price - discount,
            discount_kopecks=discount,
            idempotence_key=idempotence_key,
            raw={},
        )
        session.add(payment)
        try:
            if reserved is not None:
                await session.flush()
                session.add(
                    PromoRedemption(promo_id=reserved.id, user_id=user_id, payment_id=payment.id)
                )
            await session.commit()
        except IntegrityError:
            await session.rollback()
            payment = await find_by_key(session, user_id, idempotence_key)
            if payment is None:
                raise IdempotenceKeyConflict("Платёж с этим ключом ещё создаётся") from None
    if (
        payment.product_code != product.code
        or (await promo.payment_promo_code(session, payment.id)) != code
    ):
        raise IdempotenceKeyConflict("Ключ идемпотентности уже использован для другого платежа")
    if payment.yookassa_id:
        return payment

    body = payment_request(payment, product, email, return_url, settings)
    try:
        response = await client.create_payment(
            yookassa_idempotence_key(user_id, idempotence_key), body
        )
    except YooKassaError as error:
        if error.rejected:
            await session.delete(payment)
            await session.commit()
        raise
    payment.yookassa_id = response["id"]
    payment.raw = stored_raw(response)
    await session.commit()
    return payment


async def list_payments(session: AsyncSession, user_id: uuid.UUID) -> list[Payment]:
    result = await session.scalars(
        select(Payment)
        .where(Payment.user_id == user_id, Payment.yookassa_id.is_not(None))
        .order_by(Payment.created_at.desc(), Payment.id)
    )
    return list(result.all())


def is_refund(body: dict[str, Any]) -> bool:
    return body.get("event") == REFUND_SUCCEEDED


def notification_payment_id(body: dict[str, Any]) -> str:
    payment_object = body.get("object")
    key = "payment_id" if is_refund(body) else "id"
    yookassa_id = payment_object.get(key) if isinstance(payment_object, dict) else None
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
    if not kopecks.is_finite() or kopecks != kopecks.to_integral_value():
        return None
    return int(kopecks)


def parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    if parsed is not None and parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


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
    await extend_video_retention(session, payment.user_id, now, settings)
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
        logger.error("Сумма платежа %s не совпадает с ЮKassa, начисление отменено", payment.id)
        payment.status = PaymentStatus.canceled
        payment.raw = stored_raw(remote)
        return
    if payment.kind == PaymentKind.subscription:
        await grant_subscription(session, payment, now, settings)
    else:
        grant_package(session, payment, settings)
    payment.status = PaymentStatus.succeeded
    payment.paid_at = parse_time(remote.get("captured_at")) or now
    payment.raw = stored_raw(remote)


def awaits_notification(refund: bool) -> ColumnElement[bool]:
    if refund:
        return (Payment.status == PaymentStatus.succeeded) & ~Payment.raw.has_key("refunded_amount")
    return Payment.status == PaymentStatus.pending


async def awaits_payment(session: AsyncSession, yookassa_id: str, refund: bool) -> bool:
    return await session.scalar(
        select(exists().where(Payment.yookassa_id == yookassa_id, awaits_notification(refund)))
    )


async def load_notified_payment(
    session: AsyncSession, client: YooKassaClient, yookassa_id: str
) -> tuple[Payment | None, dict[str, Any]]:
    remote = await client.get_payment(yookassa_id)
    if remote.get("id") != yookassa_id:
        raise NotificationError("ЮKassa вернула другой платёж")
    payment = await session.scalar(
        select(Payment).where(Payment.yookassa_id == yookassa_id).with_for_update()
    )
    if payment is None:
        logger.warning("Уведомление о неизвестном платеже %s", yookassa_id)
        return None, remote
    if (remote.get("metadata") or {}).get("payment_id") != str(payment.id):
        logger.warning("Платёж %s в ЮKassa привязан к другой записи", yookassa_id)
        return None, remote
    return payment, remote


async def revoke_subscription(session: AsyncSession, payment: Payment, now: datetime) -> None:
    await session.get(User, payment.user_id, with_for_update=True)
    subscription = await session.scalar(
        select(Subscription).where(Subscription.payment_id == payment.id)
    )
    if subscription is None:
        return
    cut_at = max(subscription.starts_at, min(subscription.ends_at, now))
    removed = subscription.ends_at - cut_at
    if not removed:
        return
    later = await session.scalars(
        select(Subscription).where(
            Subscription.user_id == payment.user_id,
            Subscription.id != subscription.id,
            Subscription.starts_at >= subscription.ends_at,
        )
    )
    for next_one in later:
        next_one.starts_at -= removed
        next_one.ends_at -= removed
    subscription.ends_at = cut_at


async def revoke_package(session: AsyncSession, payment: Payment) -> None:
    await session.get(User, payment.user_id, with_for_update=True)
    packages = await session.scalars(
        select(HourPackage).where(HourPackage.payment_id == payment.id).with_for_update()
    )
    for package in packages:
        package.seconds_left = 0


async def process_refund(
    session: AsyncSession,
    client: YooKassaClient,
    yookassa_id: str,
    settings: Settings,
    now: datetime | None = None,
) -> Payment | None:
    payment, remote = await load_notified_payment(session, client, yookassa_id)
    if payment is None or payment.status != PaymentStatus.succeeded:
        return payment
    if "refunded_amount" in (payment.raw or {}):
        return payment
    refunded = parse_amount(remote.get("refunded_amount")) or 0
    if refunded < payment.amount_kopecks:
        if refunded:
            logger.warning("Частичный возврат по платежу %s, оплата не отозвана", payment.id)
        return payment
    if payment.user_id is not None:
        if payment.kind == PaymentKind.subscription:
            await revoke_subscription(session, payment, now or datetime.now(UTC))
        else:
            await revoke_package(session, payment)
    payment.status = PaymentStatus.refunded
    payment.raw = stored_raw(remote)
    report_payment(session, payment, refund=True)
    await session.commit()
    return payment


async def process_notification(
    session: AsyncSession,
    client: YooKassaClient,
    yookassa_id: str,
    settings: Settings,
    now: datetime | None = None,
) -> Payment | None:
    payment, remote = await load_notified_payment(session, client, yookassa_id)
    if payment is None or payment.status != PaymentStatus.pending:
        return payment

    status = remote.get("status")
    if payment.user_id is None:
        if status == PaymentStatus.succeeded:
            payment.status = PaymentStatus.succeeded
            payment.paid_at = parse_time(remote.get("captured_at")) or now or datetime.now(UTC)
        elif status == PaymentStatus.canceled:
            payment.status = PaymentStatus.canceled
        await session.commit()
        return payment
    if status == PaymentStatus.succeeded:
        await apply_succeeded(session, payment, remote, now or datetime.now(UTC), settings)
        if payment.status == PaymentStatus.succeeded:
            report_payment(session, payment, refund=False)
    elif status == PaymentStatus.canceled:
        payment.status = PaymentStatus.canceled
        payment.raw = stored_raw(remote)
    await session.commit()
    return payment
