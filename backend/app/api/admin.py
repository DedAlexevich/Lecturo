import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import AdminUser, SessionDep, get_admin_user
from app.models import AdminAction
from app.schemas.admin import AdminGrantIn, AdminOut, AuditEntryOut, AuditPage
from app.services import admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_admin_user)])


@router.get("/audit")
async def get_audit(
    session: SessionDep,
    action: Annotated[AdminAction | None, Query()] = None,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    total, entries = await admin.audit_page(session, action, actor_id, limit, offset)
    return AuditPage(total=total, items=[AuditEntryOut.model_validate(entry) for entry in entries])


@router.get("/admins")
async def get_admins(session: SessionDep) -> list[AdminOut]:
    return [AdminOut.model_validate(user) for user in await admin.list_admins(session)]


@router.post(
    "/admins",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Пользователь не найден"},
        status.HTTP_409_CONFLICT: {"description": "Пользователь уже администратор"},
    },
)
async def add_admin(body: AdminGrantIn, actor: AdminUser, session: SessionDep) -> AdminOut:
    target = await admin.find_user(session, body.identifier)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, admin.USER_NOT_FOUND)
    await admin.grant_admin(session, actor, target, "panel")
    return AdminOut.model_validate(target)


@router.delete(
    "/admins/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Этот пользователь не администратор"},
        status.HTTP_409_CONFLICT: {"description": "Нельзя снять последнего администратора"},
    },
)
async def remove_admin(user_id: uuid.UUID, actor: AdminUser, session: SessionDep) -> None:
    await admin.revoke_admin(session, actor, user_id)
