from typing import Any

from fastapi import APIRouter

from app.core.deps import CurrentUser, SessionDep
from app.core.errors import not_ready
from app.schemas.billing import (
    PaymentIn,
    PaymentOut,
    ProductOut,
    QueuePlanIn,
    QuotaOut,
    WaitingOut,
)
from app.services import quota

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/quota")
async def get_quota(user: CurrentUser, session: SessionDep) -> QuotaOut:
    result = await quota.get_quota(session, user)
    await session.commit()
    return QuotaOut.model_validate(result)


@router.get("/products")
async def list_products() -> list[ProductOut]:
    return quota.list_products()


@router.post("/payments")
async def create_payment(body: PaymentIn, user: CurrentUser) -> PaymentOut:
    not_ready()


@router.get("/payments")
async def list_payments(user: CurrentUser) -> list[PaymentOut]:
    not_ready()


@router.post("/webhook", include_in_schema=False)
async def yookassa_webhook(body: dict[str, Any]) -> dict[str, str]:
    not_ready()


@router.get("/waiting")
async def get_waiting(user: CurrentUser) -> WaitingOut:
    not_ready()


@router.post("/queue-plan")
async def apply_queue_plan(body: QueuePlanIn, user: CurrentUser) -> WaitingOut:
    not_ready()
