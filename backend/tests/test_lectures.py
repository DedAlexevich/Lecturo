import uuid

import pytest

from app.api import lectures as lectures_api
from app.core.db import SessionLocal, engine
from app.models import (
    Chapter,
    Lecture,
    LectureStatus,
    ProcessingStep,
    SourceType,
    StepName,
    StepStatus,
    Summary,
    TranscriptSegment,
    User,
)
from app.pipeline.download import LinkError, LinkInfo


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


async def test_foreign_lecture_status_hidden(client, auth_headers):
    async with SessionLocal() as session:
        stranger = User(display_name="Чужой")
        session.add(stranger)
        await session.flush()
        lecture = Lecture(owner_id=stranger.id, title="Чужая", source_type=SourceType.upload)
        session.add(lecture)
        await session.commit()

    response = await client.get(f"/api/v1/lectures/{lecture.id}/status", headers=auth_headers)
    assert response.status_code == 404

    async with SessionLocal() as session:
        await session.delete(await session.get(User, stranger.id))
        await session.commit()


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
