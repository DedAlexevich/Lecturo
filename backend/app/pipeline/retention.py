import asyncio
import logging
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.models import Lecture

logger = logging.getLogger(__name__)


async def extend_video_retention(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, settings: Settings
) -> None:
    subscription_expiry = now + timedelta(days=settings.subscription_video_retention_days)
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
            try:
                await asyncio.to_thread(Path(lecture.video_path).unlink, missing_ok=True)
            except OSError:
                logger.exception("Не удалось удалить видео лекции %s", lecture.id)
                continue
            lecture.video_path = None
            deleted += 1
        await session.commit()
    return deleted


async def delete_stale_uploads(ctx: dict) -> int:
    settings = get_settings()
    cutoff = time.time() - settings.upload_stale_hours * 3600
    return await asyncio.to_thread(remove_stale_uploads, settings.storage_dir / "uploads", cutoff)


def remove_stale_uploads(directory: Path, cutoff: float) -> int:
    uploads: dict[str, list[Path]] = defaultdict(list)
    for path in directory.glob("*"):
        if path.is_file():
            uploads[path.name.partition(".")[0]].append(path)
    removed = 0
    for upload_id, paths in uploads.items():
        try:
            if max(path.stat().st_mtime for path in paths) >= cutoff:
                continue
            for path in paths:
                path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Не удалось удалить брошенную загрузку %s", upload_id)
            continue
        removed += 1
    return removed
