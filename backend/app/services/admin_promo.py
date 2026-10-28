import secrets
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminAction, Payment, PaymentStatus, PromoCode, PromoRedemption, User
from app.schemas.promo import PromoCodeOut, PromoCreateIn, PromoRedemptionOut
from app.services.admin import record_action, user_label
from app.services.promo import active_redemptions, normalize_code

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
GENERATED_LENGTH = 8
LIST_LIMIT = 200
CODE_TAKEN = "Такой промокод уже есть"
PROMO_NOT_FOUND = "Промокод не найден"
ALREADY_DISABLED = "Промокод уже отключён"
VALID_UNTIL_PAST = "Срок действия уже прошёл"


def generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(GENERATED_LENGTH))


def redeemed_counts():
    return (
        select(PromoRedemption.promo_id, func.count().label("redeemed"))
        .outerjoin(Payment, Payment.id == PromoRedemption.payment_id)
        .where(or_(PromoRedemption.payment_id.is_(None), Payment.status != PaymentStatus.canceled))
        .group_by(PromoRedemption.promo_id)
        .subquery()
    )


def code_out(promo: PromoCode, redeemed: int) -> PromoCodeOut:
    fields = {
        name: getattr(promo, name) for name in PromoCodeOut.model_fields if name != "redeemed"
    }
    return PromoCodeOut(**fields, redeemed=redeemed)


async def list_codes(session: AsyncSession) -> list[PromoCodeOut]:
    counts = redeemed_counts()
    rows = await session.execute(
        select(PromoCode, func.coalesce(counts.c.redeemed, 0))
        .outerjoin(counts, counts.c.promo_id == PromoCode.id)
        .order_by(PromoCode.created_at.desc(), PromoCode.id)
        .limit(LIST_LIMIT)
    )
    return [code_out(promo, redeemed) for promo, redeemed in rows]


def describe(promo: PromoCode) -> dict:
    values = {
        "kind": promo.kind,
        "hours": promo.hours,
        "days": promo.days,
        "discount_percent": promo.discount_percent,
        "discount_kopecks": promo.discount_kopecks,
        "max_redemptions": promo.max_redemptions,
        "valid_until": promo.valid_until.isoformat() if promo.valid_until else None,
    }
    return {name: value for name, value in values.items() if value is not None}


async def create_code(
    session: AsyncSession, actor: User, body: PromoCreateIn, now: datetime | None = None
) -> PromoCodeOut:
    now = now or datetime.now(UTC)
    if body.valid_until is not None and body.valid_until <= now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, VALID_UNTIL_PAST)
    promo = PromoCode(
        code=normalize_code(body.code) if body.code else generate_code(),
        kind=body.kind,
        hours=body.hours,
        days=body.days,
        discount_percent=body.discount_percent,
        discount_kopecks=body.discount_kopecks,
        max_redemptions=body.max_redemptions,
        valid_until=body.valid_until,
        note=body.note.strip(),
        created_by=actor.id,
    )
    session.add(promo)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CODE_TAKEN) from error
    record_action(
        session,
        actor,
        AdminAction.promo_created,
        "promo",
        str(promo.id),
        promo.code,
        describe(promo),
    )
    await session.commit()
    return code_out(promo, 0)


async def disable_code(
    session: AsyncSession, actor: User, promo_id: uuid.UUID, now: datetime | None = None
) -> PromoCodeOut:
    promo = await session.get(PromoCode, promo_id, with_for_update=True)
    if promo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, PROMO_NOT_FOUND)
    if promo.disabled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, ALREADY_DISABLED)
    promo.disabled_at = now or datetime.now(UTC)
    record_action(session, actor, AdminAction.promo_disabled, "promo", str(promo.id), promo.code)
    await session.commit()
    return code_out(promo, await session.scalar(active_redemptions(promo.id)))


async def list_redemptions(session: AsyncSession, promo_id: uuid.UUID) -> list[PromoRedemptionOut]:
    if await session.get(PromoCode, promo_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, PROMO_NOT_FOUND)
    rows = await session.execute(
        select(PromoRedemption, User, Payment)
        .join(User, User.id == PromoRedemption.user_id)
        .outerjoin(Payment, Payment.id == PromoRedemption.payment_id)
        .where(PromoRedemption.promo_id == promo_id)
        .order_by(PromoRedemption.created_at.desc(), PromoRedemption.id)
        .limit(LIST_LIMIT)
    )
    return [
        PromoRedemptionOut(
            created_at=redemption.created_at,
            user_id=user.id,
            user_label=user_label(user),
            payment_status=payment.status if payment else None,
            payment_amount_kopecks=payment.amount_kopecks if payment else None,
            discount_kopecks=payment.discount_kopecks if payment else None,
        )
        for redemption, user, payment in rows
    ]
