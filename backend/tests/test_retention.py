from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import Lecture, SourceType, TranscriptSegment
from app.pipeline.retention import delete_expired_videos, extend_video_retention

SETTINGS = Settings(free_video_retention_days=3, subscription_video_retention_days=30)


async def add_lecture(user, video_path, expires_at) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Лекция",
            source_type=SourceType.upload,
            video_path=str(video_path) if video_path else None,
            video_expires_at=expires_at,
        )
        session.add(lecture)
        await session.flush()
        session.add(TranscriptSegment(lecture_id=lecture.id, idx=0, start=0, end=1, text="раз"))
        await session.commit()
        return lecture


async def reload(lecture: Lecture) -> Lecture:
    async with SessionLocal() as session:
        return await session.get(Lecture, lecture.id)


async def test_expired_video_is_deleted_and_transcript_kept(user, tmp_path):
    now = datetime.now(UTC)
    expired_file = tmp_path / "expired.mp4"
    fresh_file = tmp_path / "fresh.mp4"
    expired_file.write_bytes(b"video")
    fresh_file.write_bytes(b"video")
    expired = await add_lecture(user, expired_file, now - timedelta(minutes=1))
    fresh = await add_lecture(user, fresh_file, now + timedelta(days=1))

    deleted = await delete_expired_videos({})

    assert deleted >= 1
    assert not expired_file.exists()
    assert fresh_file.exists()
    assert (await reload(expired)).video_path is None
    assert (await reload(fresh)).video_path == str(fresh_file)
    async with SessionLocal() as session:
        texts = await session.scalars(
            select(TranscriptSegment.text).where(TranscriptSegment.lecture_id == expired.id)
        )
        assert texts.all() == ["раз"]


async def test_missing_video_file_is_cleared(user, tmp_path):
    lecture = await add_lecture(
        user, tmp_path / "gone.mp4", datetime.now(UTC) - timedelta(minutes=1)
    )

    await delete_expired_videos({})

    assert (await reload(lecture)).video_path is None


async def test_subscription_extends_uploaded_videos(user, tmp_path):
    now = datetime.now(UTC)
    recent = await add_lecture(user, tmp_path / "a.mp4", now + timedelta(days=1))
    long_kept = now + timedelta(days=60)
    kept = await add_lecture(user, tmp_path / "b.mp4", long_kept)
    deleted = await add_lecture(user, None, None)

    async with SessionLocal() as session:
        await extend_video_retention(session, user.id, now, SETTINGS)
        await session.commit()

    assert (await reload(recent)).video_expires_at == now + timedelta(days=30)
    assert (await reload(kept)).video_expires_at == long_kept
    assert (await reload(deleted)).video_expires_at is None
