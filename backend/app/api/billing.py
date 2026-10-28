import logging
import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep
from app.models import PaymentStatus
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
from app.services import quota, yookassa

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
    await session.commit()
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
    return yookassa.payment_out(payment)


@router.get("/payments")
async def list_payments(user: CurrentUser, session: SessionDep) -> list[PaymentOut]:
    payments = await yookassa.list_payments(session, user.id)
    return [yookassa.payment_out(payment) for payment in payments]


@router.post("/webhook", include_in_schema=False)
async def yookassa_webhook(
    body: dict[str, Any], session: SessionDep, yookassa_factory: YooKassaFactory
) -> dict[str, str]:
    try:
        yookassa_id = yookassa.notification_payment_id(body)
    except yookassa.NotificationError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    refund = yookassa.is_refund(body)
    awaited = PaymentStatus.succeeded if refund else PaymentStatus.pending
    if not await yookassa.has_payment(session, yookassa_id, awaited):
        return {"status": "ok"}
    process = yookassa.process_refund if refund else yookassa.process_notification
    try:
        client = yookassa_factory()
    except ValueError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Оплата недоступна") from error
    try:
        await process(session, client, yookassa_id, get_settings())
    except yookassa.NotificationError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    except yookassa.PaymentError as error:
        logger.error("Не удалось начислить оплату %s: %s", yookassa_id, error)
        raise HTTPException(422, str(error)) from error
    except yookassa.YooKassaError as error:
        if error.rejected:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Платёж не найден в ЮKassa") from error
        logger.error("Не удалось проверить платёж %s в ЮKassa: %s", yookassa_id, error)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "ЮKassa недоступна, повторите позже"
        ) from error
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
    result = await waiting_out(user, session)
    await session.commit()
    return result


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
