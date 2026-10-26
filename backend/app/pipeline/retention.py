import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Lecture


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
