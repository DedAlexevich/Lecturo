import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select

from app.api import lectures as lectures_api
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models import (
    Chapter,
    HourPackage,
    Lecture,
    LectureStatus,
    ProcessingStep,
    SourceType,
    StepName,
    StepStatus,
    Summary,
    TranscriptSegment,
    UsageEntry,
    User,
)
from app.pipeline.download import LinkError, LinkInfo
from app.services import quota


async def test_lectures_require_auth(client):
    response = await client.get("/api/v1/lectures")
    assert response.status_code == 401


async def test_lecture_detail(client, user, auth_headers):
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title="Матанализ", source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        session.add_all(
            [
                TranscriptSegment(lecture_id=lecture.id, idx=1, start=5.0, end=9.0, text="два"),
                TranscriptSegment(lecture_id=lecture.id, idx=0, start=0.0, end=4.0, text="раз"),
                Chapter(lecture_id=lecture.id, idx=0, start=0.0, end=9.0, title="Введение"),
                Summary(lecture_id=lecture.id, content_md="# Конспект"),
            ]
        )
        await session.commit()

    response = await client.get(f"/api/v1/lectures/{lecture.id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert [s["text"] for s in body["segments"]] == ["раз", "два"]
    assert body["chapters"][0]["title"] == "Введение"
    assert body["summary"]["content_md"] == "# Конспект"
    assert body["video_url"] is None

    listed = await client.get("/api/v1/lectures", headers=auth_headers)
    assert [item["id"] for item in listed.json()] == [str(lecture.id)]


async def test_foreign_lecture_hidden(client, auth_headers):
    response = await client.get(f"/api/v1/lectures/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404


async def test_lecture_status(client, user, auth_headers):
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Физика",
            source_type=SourceType.upload,
            status=LectureStatus.processing,
        )
        session.add(lecture)
        await session.flush()
        session.add(
            ProcessingStep(
                lecture_id=lecture.id,
                step=StepName.audio,
                status=StepStatus.running,
                progress=0.4,
                attempts=1,
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/lectures/{lecture.id}/status", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {
        "id": str(lecture.id),
        "status": "processing",
        "queue_position": None,
        "steps": [{"step": "audio", "status": "running", "progress": 0.4, "error": None}],
    }


@pytest.fixture
async def stranger() -> AsyncIterator[User]:
    async with SessionLocal() as session:
        stranger = User(display_name="Чужой")
        session.add(stranger)
        await session.commit()
        yield stranger
        await session.delete(stranger)
        await session.commit()


async def test_foreign_lecture_status_hidden(client, auth_headers, stranger):
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=stranger.id, title="Чужая", source_type=SourceType.upload)
        session.add(lecture)
        await session.commit()

    response = await client.get(f"/api/v1/lectures/{lecture.id}/status", headers=auth_headers)
    assert response.status_code == 404


@pytest.fixture
def link_info(monkeypatch):
    found = {"info": LinkInfo(title="Лекция 5", duration=3000.0, embed_url=None)}
    enqueued = []

    async def fake_inspect(url):
        found["connections_during_network"] = engine.pool.checkedout()
        if isinstance(found["info"], LinkError):
            raise found["info"]
        return found["info"]

    async def fake_enqueue(lecture_id):
        enqueued.append(lecture_id)

    monkeypatch.setattr(lectures_api, "inspect_link", fake_inspect)
    monkeypatch.setattr(lectures_api, "enqueue_lecture", fake_enqueue)
    found["enqueued"] = enqueued
    return found


async def test_add_link_creates_queued_lecture(client, auth_headers, link_info):
    link_info["info"] = LinkInfo(
        title="Лекция 5",
        duration=3000.0,
        embed_url="https://vkvideo.ru/video_ext.php?oid=-1&id=2",
    )

    response = await client.post(
        "/api/v1/lectures/link",
        json={"url": "https://vkvideo.ru/video-1_2"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Лекция 5"
    assert body["source_type"] == "link"
    assert body["source_url"] == "https://vkvideo.ru/video-1_2"
    assert body["embed_url"] == "https://vkvideo.ru/video_ext.php?oid=-1&id=2"
    assert body["duration_sec"] == 3000.0
    assert body["status"] == "queued"
    assert link_info["enqueued"] == [uuid.UUID(body["id"])]
    assert link_info["connections_during_network"] == 0


async def test_add_link_rejects_long_video(client, auth_headers, link_info):
    link_info["info"] = LinkError("Видео длиннее 4 часов")

    response = await client.post(
        "/api/v1/lectures/link",
        json={"url": "https://rutube.ru/video/0123456789abcdef0123456789abcdef/"},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Видео длиннее 4 часов"
    assert link_info["enqueued"] == []


async def test_add_link_puts_lecture_into_course(client, auth_headers, link_info):
    course = await client.post("/api/v1/courses", json={"title": "Физика"}, headers=auth_headers)
    course_id = course.json()["id"]

    response = await client.post(
        "/api/v1/lectures/link",
        json={"url": "https://disk.yandex.ru/i/AbCdEf", "title": "Своё", "course_id": course_id},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Своё"
    lectures = await client.get(f"/api/v1/courses/{course_id}/lectures", headers=auth_headers)
    assert [item["id"] for item in lectures.json()] == [response.json()["id"]]


async def test_add_link_to_foreign_course(client, auth_headers, link_info):
    response = await client.post(
        "/api/v1/lectures/link",
        json={"url": "https://vkvideo.ru/video-1_2", "course_id": str(uuid.uuid4())},
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert link_info["enqueued"] == []


async def test_add_link_publishes_failed_when_queue_is_down(
    client, user, auth_headers, link_info, monkeypatch
):
    published = []

    async def queue_down(lecture_id):
        raise ConnectionRefusedError

    async def fake_publish(lecture_id, user_id, status, error=None):
        published.append((lecture_id, user_id, status, error))

    monkeypatch.setattr(lectures_api, "enqueue_lecture", queue_down)
    monkeypatch.setattr(lectures_api, "publish_status", fake_publish)
    response = await client.post(
        "/api/v1/lectures/link",
        json={"url": "https://vkvideo.ru/video-1_2"},
        headers=auth_headers,
    )

    assert response.status_code == 503
    async with SessionLocal() as session:
        lecture = await session.scalar(select(Lecture).where(Lecture.owner_id == user.id))
    assert lecture.status == LectureStatus.failed
    assert published == [
        (lecture.id, user.id, LectureStatus.failed, "Очередь недоступна, попробуйте позже")
    ]


async def test_add_link_over_quota_waits_without_queue(
    client, user, auth_headers, link_info, monkeypatch
):
    published = []

    async def fake_publish(lecture_id, user_id, status, error=None):
        published.append((lecture_id, status))

    monkeypatch.setattr(lectures_api, "publish_status", fake_publish)
    monkeypatch.setattr(get_settings(), "free_weekly_seconds", 2999)

    response = await client.post(
        "/api/v1/lectures/link",
        json={"url": "https://vkvideo.ru/video-1_2"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["status"] == "waiting_quota"
    assert link_info["enqueued"] == []
    assert published == [(uuid.UUID(response.json()["id"]), LectureStatus.waiting_quota)]


async def test_add_link_accepts_link_without_scheme(client, auth_headers, link_info):
    response = await client.post(
        "/api/v1/lectures/link",
        json={"url": "disk.yandex.ru/d/AbCdEf"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["source_url"] == "https://disk.yandex.ru/d/AbCdEf"


async def test_add_link_returns_existing_lecture_for_same_video(client, auth_headers, link_info):
    first = await client.post(
        "/api/v1/lectures/link",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers=auth_headers,
    )
    course = await client.post("/api/v1/courses", json={"title": "Физика"}, headers=auth_headers)
    course_id = course.json()["id"]

    again = await client.post(
        "/api/v1/lectures/link",
        json={"url": "youtu.be/dQw4w9WgXcQ?si=abc&t=10", "course_id": course_id},
        headers=auth_headers,
    )

    assert first.status_code == 201
    assert first.json()["existing"] is False
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["existing"] is True
    assert link_info["enqueued"] == [uuid.UUID(first.json()["id"])]
    lectures = await client.get("/api/v1/lectures", headers=auth_headers)
    assert len(lectures.json()) == 1
    in_course = await client.get(f"/api/v1/courses/{course_id}/lectures", headers=auth_headers)
    assert [item["id"] for item in in_course.json()] == [first.json()["id"]]


async def test_add_link_creates_new_lecture_after_failed_one(client, user, auth_headers, link_info):
    async with SessionLocal() as session:
        session.add(
            Lecture(
                owner_id=user.id,
                title="Упала",
                source_type=SourceType.link,
                source_url="https://youtu.be/dQw4w9WgXcQ",
                status=LectureStatus.failed,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/lectures/link",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["existing"] is False
    assert len(link_info["enqueued"]) == 1


async def test_add_link_ignores_same_link_of_other_user(client, stranger, auth_headers, link_info):
    async with SessionLocal() as session:
        session.add(
            Lecture(
                owner_id=stranger.id,
                title="Чужая",
                source_type=SourceType.link,
                source_url="https://youtu.be/dQw4w9WgXcQ",
                status=LectureStatus.ready,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/lectures/link",
        json={"url": "https://youtu.be/dQw4w9WgXcQ"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["existing"] is False


@pytest.fixture
def cancelled(monkeypatch):
    calls = []

    async def fake_cancel(lecture_id):
        calls.append(lecture_id)
        return True

    monkeypatch.setattr(lectures_api, "cancel_lecture_job", fake_cancel)
    return calls


async def create_own_lecture(user, **values) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title="Лекция", source_type=SourceType.upload, **values)
        session.add(lecture)
        await session.commit()
        return lecture


async def charge_with_package(user, lecture, seconds) -> uuid.UUID:
    async with SessionLocal() as session:
        package = HourPackage(user_id=user.id, seconds_total=3600, seconds_left=3600)
        session.add(package)
        await session.flush()
        assert await quota.charge_lecture(session, user.id, lecture.id, seconds)
        await session.commit()
        return package.id


async def usage_state(user, package_id) -> tuple[int, int]:
    async with SessionLocal() as session:
        used = await session.scalar(
            select(func.coalesce(func.sum(UsageEntry.seconds), 0)).where(
                UsageEntry.user_id == user.id
            )
        )
        package = await session.get(HourPackage, package_id)
        return used, package.seconds_left


async def test_rename_lecture(client, user, auth_headers):
    lecture = await create_own_lecture(user)

    response = await client.patch(
        f"/api/v1/lectures/{lecture.id}", headers=auth_headers, json={"title": "Линейная алгебра"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Линейная алгебра"

    async with SessionLocal() as session:
        assert (await session.get(Lecture, lecture.id)).title == "Линейная алгебра"


async def test_rename_rejects_empty_title(client, user, auth_headers):
    lecture = await create_own_lecture(user)
    response = await client.patch(
        f"/api/v1/lectures/{lecture.id}", headers=auth_headers, json={"title": ""}
    )
    assert response.status_code == 422


@pytest.fixture
async def stranger_lecture(stranger) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=stranger.id, title="Чужая", source_type=SourceType.upload)
        session.add(lecture)
        await session.commit()
        return lecture


async def test_foreign_lecture_cannot_be_changed(client, auth_headers, stranger_lecture, cancelled):
    url = f"/api/v1/lectures/{stranger_lecture.id}"
    assert (await client.patch(url, headers=auth_headers, json={"title": "Моя"})).status_code == 404
    assert (await client.delete(url, headers=auth_headers)).status_code == 404
    assert cancelled == []

    async with SessionLocal() as session:
        assert (await session.get(Lecture, stranger_lecture.id)).title == "Чужая"


async def test_missing_lecture_returns_404(client, auth_headers, cancelled):
    url = f"/api/v1/lectures/{uuid.uuid4()}"
    assert (await client.patch(url, headers=auth_headers, json={"title": "Моя"})).status_code == 404
    assert (await client.delete(url, headers=auth_headers)).status_code == 404


async def test_delete_removes_files_and_records(
    client, user, auth_headers, cancelled, tmp_path, monkeypatch
):
    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path)
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.ogg"
    video.write_bytes(b"v")
    audio.write_bytes(b"a")
    lecture = await create_own_lecture(
        user, status=LectureStatus.ready, video_path=str(video), audio_path=str(audio)
    )
    (tmp_path / "originals").mkdir()
    original = tmp_path / "originals" / str(lecture.id)
    original.write_bytes(b"o")
    (tmp_path / "tmp").mkdir()
    partial = tmp_path / "tmp" / f"{lecture.id}.part"
    partial.write_bytes(b"p")
    async with SessionLocal() as session:
        session.add_all(
            [
                TranscriptSegment(lecture_id=lecture.id, idx=0, start=0.0, end=4.0, text="раз"),
                Summary(lecture_id=lecture.id, content_md="# Конспект"),
                ProcessingStep(
                    lecture_id=lecture.id,
                    step=StepName.transcribe,
                    status=StepStatus.done,
                    attempts=1,
                    progress=1.0,
                ),
            ]
        )
        await session.commit()

    response = await client.delete(f"/api/v1/lectures/{lecture.id}", headers=auth_headers)
    assert response.status_code == 204
    assert cancelled == [lecture.id]
    assert not video.exists()
    assert not audio.exists()
    assert not original.exists()
    assert not partial.exists()

    async with SessionLocal() as session:
        assert await session.get(Lecture, lecture.id) is None
        for model in (TranscriptSegment, Summary, ProcessingStep):
            count = await session.scalar(
                select(func.count()).select_from(model).where(model.lecture_id == lecture.id)
            )
            assert count == 0


async def test_delete_before_processing_refunds_quota(client, user, auth_headers, cancelled):
    lecture = await create_own_lecture(user, status=LectureStatus.queued)
    package_id = await charge_with_package(user, lecture, 2 * 3600 + 600)
    assert await usage_state(user, package_id) == (2 * 3600 + 600, 3000)

    response = await client.delete(f"/api/v1/lectures/{lecture.id}", headers=auth_headers)
    assert response.status_code == 204
    assert await usage_state(user, package_id) == (0, 3600)


async def test_delete_after_processing_started_keeps_usage(client, user, auth_headers, cancelled):
    lecture = await create_own_lecture(user, status=LectureStatus.processing)
    package_id = await charge_with_package(user, lecture, 600)
    async with SessionLocal() as session:
        session.add(
            ProcessingStep(
                lecture_id=lecture.id,
                step=StepName.transcribe,
                status=StepStatus.running,
                attempts=1,
            )
        )
        await session.commit()

    response = await client.delete(f"/api/v1/lectures/{lecture.id}", headers=auth_headers)
    assert response.status_code == 204
    assert await usage_state(user, package_id) == (600, 3600)


async def test_delete_retried_lecture_keeps_usage(client, user, auth_headers, cancelled):
    lecture = await create_own_lecture(user, status=LectureStatus.queued)
    package_id = await charge_with_package(user, lecture, 600)
    async with SessionLocal() as session:
        session.add(
            ProcessingStep(
                lecture_id=lecture.id,
                step=StepName.summarize,
                status=StepStatus.pending,
                attempts=1,
            )
        )
        await session.commit()

    response = await client.delete(f"/api/v1/lectures/{lecture.id}", headers=auth_headers)
    assert response.status_code == 204
    assert await usage_state(user, package_id) == (600, 3600)


async def test_delete_works_when_queue_is_down(client, user, auth_headers, monkeypatch):
    async def queue_down(lecture_id):
        raise ConnectionError("redis недоступен")

    monkeypatch.setattr(lectures_api, "cancel_lecture_job", queue_down)
    lecture = await create_own_lecture(user)

    response = await client.delete(f"/api/v1/lectures/{lecture.id}", headers=auth_headers)
    assert response.status_code == 204
    async with SessionLocal() as session:
        assert await session.get(Lecture, lecture.id) is None
