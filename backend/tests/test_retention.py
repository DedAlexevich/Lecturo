import os
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.models import Lecture, SourceType, TranscriptSegment
from app.pipeline.retention import (
    delete_expired_videos,
    delete_stale_uploads,
    extend_video_retention,
)

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


async def test_failed_video_deletion_does_not_stop_batch(user, tmp_path):
    expired = datetime.now(UTC) - timedelta(minutes=1)
    stuck_path = tmp_path / "stuck.mp4"
    stuck_path.mkdir()
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"video")
    stuck = await add_lecture(user, stuck_path, expired)
    other = await add_lecture(user, video_file, expired)

    await delete_expired_videos({})

    assert stuck_path.exists()
    assert (await reload(stuck)).video_path == str(stuck_path)
    assert not video_file.exists()
    assert (await reload(other)).video_path is None


def touch(path, hours_ago: float) -> None:
    path.write_bytes(b"data")
    moment = time.time() - hours_ago * 3600
    os.utime(path, (moment, moment))


async def test_stale_uploads_are_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path)
    monkeypatch.setattr(get_settings(), "upload_stale_hours", 24)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    touch(uploads / "abandoned", 30)
    touch(uploads / "abandoned.info", 30)
    touch(uploads / "active", 1)
    touch(uploads / "active.info", 30)
    touch(uploads / "orphan.info", 48)

    removed = await delete_stale_uploads({})

    assert removed == 2
    assert sorted(path.name for path in uploads.iterdir()) == ["active", "active.info"]


async def test_stale_uploads_without_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path)

    assert await delete_stale_uploads({}) == 0


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
