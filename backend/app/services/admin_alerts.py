from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdminAction,
    AlertDelivery,
    AlertKind,
    AlertSettings,
    AlertSignal,
    AlertState,
    Payment,
    User,
)
from app.schemas.admin_alerts import AlertSettingsIn, AlertSettingsOut
from app.schemas.user import TelegramNotifications
from app.services.admin import record_action, user_label
from app.services.identities import telegram_notifications
from app.services.quota import list_products

TEST_ALERT = "Тестовый алерт Lecturo. Если вы его видите, алерты до вас доходят."
TELEGRAM_NOT_READY = (
    "Алерты приходят через бота: привяжите Telegram в кабинете и нажмите Start в боте"
)


def report(
    session: AsyncSession, kind: AlertKind, key: str, state: AlertState, text: str
) -> AlertSignal:
    signal = AlertSignal(kind=kind, key=key[:128], state=state, text=text)
    session.add(signal)
    return signal


def rubles(kopecks: int) -> str:
    whole, rest = divmod(kopecks, 100)
    return f"{whole} ₽" if rest == 0 else f"{whole},{rest:02d} ₽"


def report_payment(session: AsyncSession, payment: Payment, refund: bool) -> None:
    product = next((p for p in list_products() if p.code == payment.product_code), None)
    title = product.title if product else payment.product_code
    verb = "Возврат" if refund else "Оплата"
    report(
        session,
        AlertKind.payment,
        f"{'refund' if refund else 'payment'}:{payment.id}",
        AlertState.event,
        f"{verb}: {title}, {rubles(payment.amount_kopecks)}",
    )


async def report_webhook_error(session: AsyncSession, yookassa_id: str, reason: str) -> None:
    await session.rollback()
    report(
        session,
        AlertKind.webhook_error,
        yookassa_id,
        AlertState.event,
        f"Вебхук ЮKassa, платёж {yookassa_id}: {reason}",
    )
    await session.commit()


async def telegram_state(session: AsyncSession, user: User) -> TelegramNotifications:
    await session.refresh(user, ["identities"])
    return telegram_notifications(user.identities)


async def get_settings(session: AsyncSession, user: User) -> AlertSettingsOut:
    settings = await session.get(AlertSettings, user.id, populate_existing=True)
    muted = set(settings.muted_kinds) if settings else set()
    return AlertSettingsOut(
        enabled=settings.enabled if settings else True,
        kinds=[kind for kind in AlertKind if kind not in muted],
        recoveries=settings.recoveries if settings else True,
        telegram=await telegram_state(session, user),
    )


async def save_settings(
    session: AsyncSession, user: User, body: AlertSettingsIn
) -> AlertSettingsOut:
    settings = await session.get(AlertSettings, user.id, with_for_update=True)
    if settings is None:
        settings = AlertSettings(user_id=user.id)
        session.add(settings)
    kinds = [kind for kind in AlertKind if kind in body.kinds]
    settings.enabled = body.enabled
    settings.muted_kinds = [kind.value for kind in AlertKind if kind not in kinds]
    settings.recoveries = body.recoveries
    record_action(
        session,
        user,
        AdminAction.alert_settings_changed,
        "user",
        str(user.id),
        user_label(user),
        {
            "source": "panel",
            "enabled": body.enabled,
            "kinds": [kind.value for kind in kinds],
            "recoveries": body.recoveries,
        },
    )
    await session.commit()
    return await get_settings(session, user)


async def send_test(session: AsyncSession, user: User) -> None:
    if await telegram_state(session, user) != TelegramNotifications.ready:
        raise HTTPException(status.HTTP_409_CONFLICT, TELEGRAM_NOT_READY)
    session.add(AlertDelivery(user_id=user.id, text=TEST_ALERT))
    await session.commit()
