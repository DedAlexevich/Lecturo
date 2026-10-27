import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import Lecture


async def extend_video_retention(
    session: AsyncSession, user_id: uuid.UUID, settings: Settings
) -> None:
    subscription_expiry = Lecture.created_at + timedelta(
        days=settings.subscription_video_retention_days
    )
    await session.execute(
        update(Lecture)
        .where(
            Lecture.owner_id == user_id,
            Lecture.video_path.is_not(None),
            Lecture.video_expires_at.is_not(None),
        )
        .values(video_expires_at=func.greatest(Lecture.video_expires_at, subscription_expiry))
        .execution_options(synchronize_session=False)
    )


async def delete_expired_videos(ctx: dict) -> int:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        lectures = await session.scalars(
            select(Lecture).where(Lecture.video_path.is_not(None), Lecture.video_expires_at < now)
        )
        deleted = 0
        for lecture in lectures:
            await asyncio.to_thread(Path(lecture.video_path).unlink, missing_ok=True)
            lecture.video_path = None
            deleted += 1
        await session.commit()
    return deleted
