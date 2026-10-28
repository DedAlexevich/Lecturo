import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import AdminUser, SessionDep, get_admin_user
from app.schemas.admin_users import (
    AdminReasonIn,
    ExtendSubscriptionIn,
    GrantHoursIn,
    StatsOut,
    UserBriefOut,
    UserCardOut,
)
from app.services import admin_users
from app.services.admin_users import MOSCOW

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_admin_user)])

USER_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Пользователь не найден"}}
CONFLICT = {status.HTTP_409_CONFLICT: {"description": "Действие сейчас недоступно"}}


def today() -> date:
    return datetime.now(MOSCOW).date()


@router.get("/users")
async def search_users(
    actor: AdminUser,
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=320)],
) -> list[UserBriefOut]:
    return await admin_users.search_users(session, actor, q)


@router.get("/users/{user_id}", responses=USER_NOT_FOUND)
async def get_user_card(user_id: uuid.UUID, actor: AdminUser, session: SessionDep) -> UserCardOut:
    return await admin_users.view_user(session, actor, user_id)


@router.post("/users/{user_id}/admin", responses={**USER_NOT_FOUND, **CONFLICT})
async def make_admin(user_id: uuid.UUID, actor: AdminUser, session: SessionDep) -> UserCardOut:
    return await admin_users.make_admin(session, actor, user_id)


@router.post("/users/{user_id}/hours", responses=USER_NOT_FOUND)
async def grant_hours(
    user_id: uuid.UUID, body: GrantHoursIn, actor: AdminUser, session: SessionDep
) -> UserCardOut:
    return await admin_users.grant_hours(session, actor, user_id, body.hours, body.reason)


@router.post("/users/{user_id}/subscription", responses=USER_NOT_FOUND)
async def extend_subscription(
    user_id: uuid.UUID, body: ExtendSubscriptionIn, actor: AdminUser, session: SessionDep
) -> UserCardOut:
    return await admin_users.extend_subscription(session, actor, user_id, body.days, body.reason)


@router.post("/users/{user_id}/block", responses={**USER_NOT_FOUND, **CONFLICT})
async def block_user(
    user_id: uuid.UUID, body: AdminReasonIn, actor: AdminUser, session: SessionDep
) -> UserCardOut:
    return await admin_users.block_user(session, actor, user_id, body.reason)


@router.post("/users/{user_id}/unblock", responses={**USER_NOT_FOUND, **CONFLICT})
async def unblock_user(
    user_id: uuid.UUID, body: AdminReasonIn, actor: AdminUser, session: SessionDep
) -> UserCardOut:
    return await admin_users.unblock_user(session, actor, user_id, body.reason)


@router.get(
    "/stats",
    responses={status.HTTP_400_BAD_REQUEST: {"description": "Неверный период"}},
)
async def get_stats(
    session: SessionDep,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> StatsOut:
    end = date_to or today()
    start = date_from or end - timedelta(days=29)
    return await admin_users.cached_stats(session, start, end)
