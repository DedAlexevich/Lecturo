import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import (
    HourPackage,
    Payment,
    PaymentStatus,
    PromoCode,
    PromoKind,
    PromoRedemption,
    Subscription,
    User,
)
from app.pipeline.retention import extend_video_retention
from app.schemas.promo import PromoOut

MIN_PAYMENT_KOPECKS = 100
NOT_FOUND = "Такого промокода нет. Проверьте, как он написан"
DISABLED = "Этот промокод больше не действует"
EXPIRED = "Срок действия промокода истёк"
EXHAUSTED = "Промокод закончился: его уже использовали максимальное число раз"
ALREADY_USED = "Вы уже использовали этот промокод"
NOT_DISCOUNT = "Этот промокод не даёт скидку. Примените его в поле «Промокод» в кабинете"
ONLY_AT_PAYMENT = "Скидка применится при оплате"


class PromoError(ValueError):
    pass


def normalize_code(code: str) -> str:
    return code.strip().upper()


def active_redemptions(promo_id: uuid.UUID):
    return (
        select(func.count())
        .select_from(PromoRedemption)
        .outerjoin(Payment, Payment.id == PromoRedemption.payment_id)
        .where(
            PromoRedemption.promo_id == promo_id,
            or_(PromoRedemption.payment_id.is_(None), Payment.status != PaymentStatus.canceled),
        )
    )


async def lock_usable(
    session: AsyncSession, code: str, user_id: uuid.UUID, now: datetime
) -> PromoCode:
    promo = await session.scalar(
        select(PromoCode)
        .where(PromoCode.code == normalize_code(code))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if promo is None:
        raise PromoError(NOT_FOUND)
    if promo.disabled_at is not None:
        raise PromoError(DISABLED)
    if promo.valid_until is not None and promo.valid_until <= now:
        raise PromoError(EXPIRED)
    used_by_user = await session.scalar(
        active_redemptions(promo.id).where(PromoRedemption.user_id == user_id)
    )
    if used_by_user:
        raise PromoError(ALREADY_USED)
    if promo.max_redemptions is not None:
        used = await session.scalar(active_redemptions(promo.id))
        if used >= promo.max_redemptions:
            raise PromoError(EXHAUSTED)
    return promo


def discount_for(promo: PromoCode, price_kopecks: int) -> int:
    if promo.discount_percent is not None:
        discount = price_kopecks * promo.discount_percent // 100
    else:
        discount = promo.discount_kopecks or 0
    return max(0, min(discount, price_kopecks - MIN_PAYMENT_KOPECKS))


def promo_out(promo: PromoCode, applied: bool, message: str) -> PromoOut:
    return PromoOut(
        code=promo.code,
        kind=promo.kind,
        hours=promo.hours,
        days=promo.days,
        discount_percent=promo.discount_percent,
        discount_kopecks=promo.discount_kopecks,
        applied=applied,
        message=message,
    )


async def add_days(
    session: AsyncSession, user_id: uuid.UUID, days: int, now: datetime, settings: Settings
) -> None:
    current_end = await session.scalar(
        select(func.max(Subscription.ends_at)).where(
            Subscription.user_id == user_id, Subscription.ends_at > now
        )
    )
    starts_at = current_end or now
    ends_at = starts_at + timedelta(days=days)
    session.add(Subscription(user_id=user_id, starts_at=starts_at, ends_at=ends_at))
    await extend_video_retention(session, user_id, now, settings)


async def apply_code(
    session: AsyncSession,
    user: User,
    code: str,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> PromoOut:
    now = now or datetime.now(UTC)
    settings = settings or get_settings()
    await session.get(User, user.id, with_for_update=True)
    promo = await lock_usable(session, code, user.id, now)
    if promo.kind == PromoKind.discount:
        checked = promo_out(promo, False, ONLY_AT_PAYMENT)
        await session.rollback()
        return checked
    if promo.kind == PromoKind.hours:
        seconds = promo.hours * 3600
        session.add(HourPackage(user_id=user.id, seconds_total=seconds, seconds_left=seconds))
        message = f"Начислено {promo.hours} ч, они не сгорают"
    else:
        await add_days(session, user.id, promo.days, now, settings)
        message = f"Подписка продлена на {promo.days} дн."
    session.add(PromoRedemption(promo_id=promo.id, user_id=user.id))
    await session.commit()
    return promo_out(promo, True, message)


async def reserve_discount(
    session: AsyncSession, user_id: uuid.UUID, code: str, price_kopecks: int, now: datetime
) -> tuple[PromoCode, int]:
    promo = await lock_usable(session, code, user_id, now)
    if promo.kind != PromoKind.discount:
        raise PromoError(NOT_DISCOUNT)
    return promo, discount_for(promo, price_kopecks)


async def payment_promo_code(session: AsyncSession, payment_id: uuid.UUID) -> str | None:
    return await session.scalar(
        select(PromoCode.code)
        .join(PromoRedemption, PromoRedemption.promo_id == PromoCode.id)
        .where(PromoRedemption.payment_id == payment_id)
    )
