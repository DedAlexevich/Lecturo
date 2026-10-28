import logging
import uuid
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminAction, AdminAuditEntry, AuthIdentity, AuthProvider, User
from app.services.auth import normalize_email

logger = logging.getLogger(__name__)

SECRET_SUFFIXES = ("password", "token", "secret", "hash", "key", "signature", "init_data")
SECRET_NAMES = {*SECRET_SUFFIXES, "code", "cookie", "authorization"}
BOOTSTRAP_LOCK_ID = 429_001
ALREADY_ADMIN = "Пользователь уже администратор"
NOT_ADMIN = "Этот пользователь не администратор"
LAST_ADMIN = "Нельзя снять последнего администратора"
USER_NOT_FOUND = "Пользователь не найден"


def is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in SECRET_NAMES or lowered.endswith(
        tuple(f"_{suffix}" for suffix in SECRET_SUFFIXES)
    )


def without_secrets(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): without_secrets(item)
            for key, item in value.items()
            if not is_secret_key(str(key))
        }
    if isinstance(value, list | tuple):
        return [without_secrets(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def user_label(user: User) -> str:
    return user.email or user.display_name or str(user.id)


def record_action(
    session: AsyncSession,
    actor: User | None,
    action: AdminAction,
    target_type: str,
    target_id: str | None,
    target_label: str = "",
    details: dict | None = None,
) -> AdminAuditEntry:
    entry = AdminAuditEntry(
        actor_id=actor.id if actor else None,
        actor_label=user_label(actor) if actor else "",
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
        details=without_secrets(details or {}),
    )
    session.add(entry)
    return entry


async def find_user(session: AsyncSession, identifier: str) -> User | None:
    value = identifier.strip()
    if value.isdigit():
        return await session.scalar(
            select(User)
            .join(AuthIdentity)
            .where(
                AuthIdentity.provider == AuthProvider.telegram,
                AuthIdentity.provider_user_id == value,
            )
        )
    if "@" in value:
        return await session.scalar(select(User).where(User.email == normalize_email(value)))
    return None


async def grant_admin(session: AsyncSession, actor: User | None, target: User, source: str) -> None:
    ids = [target.id] if actor is None else [target.id, actor.id]
    locked = {
        user.id: user
        for user in await session.scalars(
            select(User)
            .where(User.id.in_(ids))
            .order_by(User.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    if actor is not None and not locked[actor.id].is_admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    if target.is_admin:
        raise HTTPException(status.HTTP_409_CONFLICT, ALREADY_ADMIN)
    target.is_admin = True
    record_action(
        session,
        actor,
        AdminAction.admin_granted,
        "user",
        str(target.id),
        user_label(target),
        {"source": source},
    )
    await session.commit()


async def revoke_admin(session: AsyncSession, actor: User, target_id: uuid.UUID) -> None:
    admins = (
        await session.scalars(
            select(User)
            .where(User.is_admin)
            .order_by(User.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    if all(admin.id != actor.id for admin in admins):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    target = next((admin for admin in admins if admin.id == target_id), None)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_ADMIN)
    if len(admins) == 1:
        raise HTTPException(status.HTTP_409_CONFLICT, LAST_ADMIN)
    target.is_admin = False
    record_action(
        session,
        actor,
        AdminAction.admin_revoked,
        "user",
        str(target.id),
        user_label(target),
        {"source": "panel"},
    )
    await session.commit()


async def list_admins(session: AsyncSession) -> list[User]:
    admins = await session.scalars(
        select(User).where(User.is_admin).order_by(User.created_at, User.id)
    )
    return list(admins.all())


async def audit_page(
    session: AsyncSession,
    action: AdminAction | None,
    actor_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[int, list[AdminAuditEntry]]:
    conditions = []
    if action is not None:
        conditions.append(AdminAuditEntry.action == action)
    if actor_id is not None:
        conditions.append(AdminAuditEntry.actor_id == actor_id)
    total = await session.scalar(
        select(func.count()).select_from(AdminAuditEntry).where(*conditions)
    )
    entries = await session.scalars(
        select(AdminAuditEntry)
        .where(*conditions)
        .order_by(AdminAuditEntry.created_at.desc(), AdminAuditEntry.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return total or 0, list(entries.all())


def parse_identifiers(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


async def bootstrap_admins(session: AsyncSession, identifiers: Iterable[str]) -> int:
    await session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": BOOTSTRAP_LOCK_ID})
    if await session.scalar(select(User.id).where(User.is_admin).limit(1)) is not None:
        await session.commit()
        return 0
    granted = 0
    for identifier in identifiers:
        user = await find_user(session, identifier)
        if user is None:
            logger.warning("INITIAL_ADMINS: user not found")
            continue
        user.is_admin = True
        record_action(
            session,
            None,
            AdminAction.admin_granted,
            "user",
            str(user.id),
            user_label(user),
            {"source": "env"},
        )
        granted += 1
    await session.commit()
    return granted
