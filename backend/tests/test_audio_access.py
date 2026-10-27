import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from app.core.db import SessionLocal
from app.models import Lecture, LectureStatus, ProcessingStep, SourceType, StepName, StepStatus
from app.pipeline.video_access import media_signature, signed_audio_url


async def create_lecture(
    owner_id: uuid.UUID,
    audio_path: Path | None,
    *,
    video_step: StepStatus = StepStatus.done,
    video_path: str | None = None,
    video_expires_at: datetime | None = None,
    source_type: SourceType = SourceType.upload,
) -> uuid.UUID:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=owner_id,
            title="Лекция в mp3",
            status=LectureStatus.ready,
            source_type=source_type,
            audio_path=str(audio_path) if audio_path else None,
            video_path=video_path,
            video_expires_at=video_expires_at,
        )
        session.add(lecture)
        await session.flush()
        session.add(ProcessingStep(lecture_id=lecture.id, step=StepName.video, status=video_step))
        await session.commit()
        return lecture.id


def audio_file(tmp_path: Path) -> Path:
    path = tmp_path / "lecture.opus"
    path.write_bytes(b"OggS" + bytes(64))
    return path


async def test_audio_upload_gets_audio_url(client, user, auth_headers, tmp_path):
    path = audio_file(tmp_path)
    lecture_id = await create_lecture(user.id, path)
    body = (await client.get(f"/api/v1/lectures/{lecture_id}", headers=auth_headers)).json()
    assert body["audio_only"] is True
    assert body["video_url"] is None

    response = await client.get(body["audio_url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/ogg"
    assert response.content == path.read_bytes()


async def test_audio_supports_range(client, user, tmp_path):
    lecture_id = await create_lecture(user.id, audio_file(tmp_path))
    response = await client.get(signed_audio_url(lecture_id), headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"OggS"


async def test_not_audio_only_while_processing(client, user, auth_headers, tmp_path):
    lecture_id = await create_lecture(user.id, audio_file(tmp_path), video_step=StepStatus.running)
    body = (await client.get(f"/api/v1/lectures/{lecture_id}", headers=auth_headers)).json()
    assert body["audio_only"] is False
    assert body["audio_url"] is None


async def test_expired_video_is_not_audio_only(client, user, auth_headers, tmp_path):
    lecture_id = await create_lecture(
        user.id, audio_file(tmp_path), video_expires_at=datetime.now(UTC) - timedelta(days=1)
    )
    body = (await client.get(f"/api/v1/lectures/{lecture_id}", headers=auth_headers)).json()
    assert body["audio_only"] is False


async def test_link_is_not_audio_only(client, user, auth_headers, tmp_path):
    lecture_id = await create_lecture(user.id, audio_file(tmp_path), source_type=SourceType.link)
    body = (await client.get(f"/api/v1/lectures/{lecture_id}", headers=auth_headers)).json()
    assert body["audio_only"] is False


async def test_audio_without_signature_forbidden(client, user, tmp_path):
    lecture_id = await create_lecture(user.id, audio_file(tmp_path))
    response = await client.get(f"/api/v1/lectures/{lecture_id}/audio")
    assert response.status_code == 403


async def test_video_signature_does_not_open_audio(client, user, tmp_path):
    lecture_id = await create_lecture(user.id, audio_file(tmp_path))
    expires = int(time.time()) + 600
    signature = media_signature("video", lecture_id, expires, None)
    response = await client.get(
        f"/api/v1/lectures/{lecture_id}/audio",
        params={"expires": expires, "signature": signature},
    )
    assert response.status_code == 403


async def test_audio_signature_bound_to_lecture(client, user, tmp_path):
    lecture_id = await create_lecture(user.id, audio_file(tmp_path))
    other_id = await create_lecture(user.id, audio_file(tmp_path))
    query = urlsplit(signed_audio_url(other_id)).query
    response = await client.get(f"/api/v1/lectures/{lecture_id}/audio?{query}")
    assert response.status_code == 403


async def test_missing_audio_file(client, user, tmp_path):
    lecture_id = await create_lecture(user.id, tmp_path / "gone.opus")
    response = await client.get(signed_audio_url(lecture_id))
    assert response.status_code == 404
