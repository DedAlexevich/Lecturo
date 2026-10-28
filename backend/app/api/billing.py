import logging
import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep
from app.models import BusinessEventKind, Payment, PaymentKind, PaymentStatus
from app.pipeline.events import publish_status
from app.pipeline.tasks import enqueue_lecture
from app.schemas.billing import (
    PaymentIn,
    PaymentOut,
    ProductOut,
    QueuePlanIn,
    QuotaOut,
    WaitingLectureOut,
    WaitingOut,
)
from app.services import business_events, quota, yookassa

router = APIRouter(prefix="/billing", tags=["billing"])
logger = logging.getLogger(__name__)


def get_yookassa_factory() -> Callable[[], yookassa.YooKassaClient]:
    return lambda: yookassa.YooKassaClient(get_settings())


YooKassaFactory = Annotated[Callable[[], yookassa.YooKassaClient], Depends(get_yookassa_factory)]


def resolve_return_url(return_url: str | None) -> str:
    public_url = get_settings().public_url.rstrip("/")
    if return_url is None:
        return f"{public_url}/account"
    if return_url != public_url and not return_url.startswith(f"{public_url}/"):
        raise HTTPException(422, "Адрес возврата должен вести на сайт Lecturo")
    return return_url


@router.get("/quota")
async def get_quota(user: CurrentUser, session: SessionDep) -> QuotaOut:
    result = await quota.get_quota(session, user)
    return QuotaOut.model_validate(result)


@router.get("/products")
async def list_products() -> list[ProductOut]:
    return quota.list_products()


@router.post("/payments")
async def create_payment(
    body: PaymentIn,
    user: CurrentUser,
    session: SessionDep,
    yookassa_factory: YooKassaFactory,
    idempotence_key: Annotated[
        str | None, Header(alias="Idempotence-Key", min_length=1, max_length=64)
    ] = None,
) -> PaymentOut:
    if not body.accept_offer:
        raise HTTPException(422, "Нужно принять условия оферты")
    product = next((p for p in quota.list_products() if p.code == body.product_code), None)
    if product is None:
        raise HTTPException(422, "Нет такого тарифа")
    return_url = resolve_return_url(body.return_url)
    try:
        client = yookassa_factory()
    except ValueError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Оплата недоступна") from error
    try:
        payment = await yookassa.create_payment(
            session,
            client,
            user,
            product,
            idempotence_key or str(uuid.uuid4()),
            return_url,
            get_settings(),
            body.receipt_email,
        )
    except yookassa.IdempotenceKeyConflict as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except yookassa.PaymentError as error:
        raise HTTPException(422, str(error)) from error
    except yookassa.YooKassaError as error:
        logger.error("Не удалось создать платёж в ЮKassa: %s", error)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Не удалось создать платёж, попробуйте позже"
        ) from error
    await business_events.record_event(
        BusinessEventKind.payment_created,
        user,
        payment_kind=payment.kind,
        product=payment.product_code,
        amount_kopecks=payment.amount_kopecks,
        yookassa_id=payment.yookassa_id,
    )
    return yookassa.payment_out(payment)


@router.get("/payments")
async def list_payments(user: CurrentUser, session: SessionDep) -> list[PaymentOut]:
    payments = await yookassa.list_payments(session, user.id)
    return [yookassa.payment_out(payment) for payment in payments]


OUTCOME_EVENTS = {
    PaymentStatus.succeeded: BusinessEventKind.payment_succeeded,
    PaymentStatus.canceled: BusinessEventKind.payment_canceled,
    PaymentStatus.refunded: BusinessEventKind.payment_refunded,
}


async def record_payment_outcome(payment: Payment | None) -> None:
    kind = OUTCOME_EVENTS.get(payment.status) if payment else None
    if payment is None or kind is None:
        return
    details = {
        "payment_kind": payment.kind,
        "product": payment.product_code,
        "amount_kopecks": payment.amount_kopecks,
        "yookassa_id": payment.yookassa_id,
    }
    await business_events.record_event(kind, user_id=payment.user_id, **details)
    if kind == BusinessEventKind.payment_succeeded and payment.kind == PaymentKind.subscription:
        await business_events.record_event(
            BusinessEventKind.subscription_granted, user_id=payment.user_id, **details
        )


async def reject_webhook(yookassa_id: str | None, reason: str) -> None:
    await business_events.record_event(
        BusinessEventKind.webhook_rejected, yookassa_id=yookassa_id, reason=reason
    )


@router.post("/webhook", include_in_schema=False)
async def yookassa_webhook(
    body: dict[str, Any], session: SessionDep, yookassa_factory: YooKassaFactory
) -> dict[str, str]:
    try:
        yookassa_id = yookassa.notification_payment_id(body)
    except yookassa.NotificationError as error:
        await reject_webhook(None, str(error))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    refund = yookassa.is_refund(body)
    if not await yookassa.awaits_payment(session, yookassa_id, refund):
        return {"status": "ok"}
    await business_events.record_event(
        BusinessEventKind.webhook_received, event=body.get("event"), yookassa_id=yookassa_id
    )
    process = yookassa.process_refund if refund else yookassa.process_notification
    try:
        client = yookassa_factory()
    except ValueError as error:
        await reject_webhook(yookassa_id, "Оплата недоступна")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Оплата недоступна") from error
    try:
        payment = await process(session, client, yookassa_id, get_settings())
    except yookassa.NotificationError as error:
        await reject_webhook(yookassa_id, str(error))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    except yookassa.PaymentError as error:
        logger.error("Не удалось начислить оплату %s: %s", yookassa_id, error)
        await reject_webhook(yookassa_id, str(error))
        raise HTTPException(422, str(error)) from error
    except yookassa.YooKassaError as error:
        await reject_webhook(yookassa_id, str(error))
        if error.rejected:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Платёж не найден в ЮKassa") from error
        logger.error("Не удалось проверить платёж %s в ЮKassa: %s", yookassa_id, error)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "ЮKassa недоступна, повторите позже"
        ) from error
    await record_payment_outcome(payment)
    return {"status": "ok"}


async def waiting_out(user: CurrentUser, session: SessionDep) -> WaitingOut:
    lectures = await quota.list_waiting(session, user.id)
    result = await quota.get_quota(session, user)
    return WaitingOut(
        lectures=[WaitingLectureOut.model_validate(lecture) for lecture in lectures],
        available_sec=result.available_sec,
        resets_at=result.resets_at,
    )


@router.get("/waiting")
async def get_waiting(user: CurrentUser, session: SessionDep) -> WaitingOut:
    return await waiting_out(user, session)


@router.post("/queue-plan")
async def apply_queue_plan(body: QueuePlanIn, user: CurrentUser, session: SessionDep) -> WaitingOut:
    try:
        planned = await quota.plan_queue(session, user, body.lecture_ids)
    except (quota.PlanExceedsQuota, quota.LectureNotWaiting) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except quota.QueuePlanError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    await session.commit()
    for lecture in planned:
        await publish_status(lecture.id, user.id, lecture.status)

    for index, lecture in enumerate(planned):
        try:
            await enqueue_lecture(lecture.id)
        except (OSError, RedisError) as error:
            returned = planned[index:]
            await quota.return_to_waiting(session, returned)
            await session.commit()
            for waiting in returned:
                await publish_status(waiting.id, user.id, waiting.status)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Очередь недоступна, попробуйте позже"
            ) from error

    result = await waiting_out(user, session)
    await session.commit()
    return result
