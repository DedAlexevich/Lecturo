import uuid

from fastapi import APIRouter, Depends, status

from app.core.deps import AdminUser, SessionDep, get_admin_user
from app.schemas.promo import PromoCodeOut, PromoCreateIn, PromoRedemptionOut
from app.services import admin_promo

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_admin_user)])

PROMO_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Промокод не найден"}}


@router.get("/promo-codes")
async def list_promo_codes(session: SessionDep) -> list[PromoCodeOut]:
    return await admin_promo.list_codes(session)


@router.post(
    "/promo-codes",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "Такой промокод уже есть"}},
)
async def create_promo_code(
    body: PromoCreateIn, actor: AdminUser, session: SessionDep
) -> PromoCodeOut:
    return await admin_promo.create_code(session, actor, body)


@router.post(
    "/promo-codes/{promo_id}/disable",
    responses={
        **PROMO_NOT_FOUND,
        status.HTTP_409_CONFLICT: {"description": "Промокод уже отключён"},
    },
)
async def disable_promo_code(
    promo_id: uuid.UUID, actor: AdminUser, session: SessionDep
) -> PromoCodeOut:
    return await admin_promo.disable_code(session, actor, promo_id)


@router.get("/promo-codes/{promo_id}/redemptions", responses=PROMO_NOT_FOUND)
async def list_promo_redemptions(
    promo_id: uuid.UUID, session: SessionDep
) -> list[PromoRedemptionOut]:
    return await admin_promo.list_redemptions(session, promo_id)
