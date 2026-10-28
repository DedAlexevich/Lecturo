import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import BusinessEvent, BusinessEventKind, User
from app.services.admin import user_label

logger = logging.getLogger(__name__)


async def record_event(
    kind: BusinessEventKind,
    user: User | None = None,
    user_id: uuid.UUID | None = None,
    label: str = "",
    **details: object,
) -> None:
    try:
        async with SessionLocal() as session:
            session.add(
                BusinessEvent(
                    kind=kind,
                    user_id=user.id if user else user_id,
                    user_label=user_label(user) if user else label,
                    details={
                        key: str(value) for key, value in details.items() if value is not None
                    },
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Не удалось записать событие %s", kind)


async def events_page(
    session: AsyncSession,
    kind: BusinessEventKind | None,
    user_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[int, list[BusinessEvent]]:
    query = select(BusinessEvent)
    count = select(func.count()).select_from(BusinessEvent)
    if kind is not None:
        query = query.where(BusinessEvent.kind == kind)
        count = count.where(BusinessEvent.kind == kind)
    if user_id is not None:
        query = query.where(BusinessEvent.user_id == user_id)
        count = count.where(BusinessEvent.user_id == user_id)
    total = await session.scalar(count) or 0
    rows = await session.scalars(
        query.order_by(BusinessEvent.created_at.desc()).limit(limit).offset(offset)
    )
    return total, list(rows)
