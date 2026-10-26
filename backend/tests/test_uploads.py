import json
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.api import uploads as uploads_api
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Lecture, LectureStatus, SourceType, course_lectures

HOOKS_URL = "/api/v1/uploads/hooks"


def hook(kind: str, headers: dict[str, str], **upload) -> dict:
    return {
        "Type": kind,
        "Event": {
            "Upload": upload,
            "HTTPRequest": {"Header": {name: [value] for name, value in headers.items()}},
        },
    }


@pytest.fixture
def storage(monkeypatch, tmp_path) -> Path:
    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path)
    (tmp_path / "uploads").mkdir()
    return tmp_path


@pytest.fixture
def enqueued(monkeypatch) -> list[uuid.UUID]:
    queued: list[uuid.UUID] = []

    async def fake_enqueue(lecture_id):
        queued.append(lecture_id)

    monkeypatch.setattr(uploads_api, "enqueue_lecture", fake_enqueue)
    return queued


def put_upload(storage: Path, upload_id: str, source: Path) -> Path:
    path = storage / "uploads" / upload_id
    source.rename(path)
    (storage / "uploads" / f"{upload_id}.info").write_text(
        json.dumps({"ID": upload_id, "Size": path.stat().st_size})
    )
    return path


def sample_audio(tmp_path: Path, seconds: int = 2) -> Path:
    path = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )
    return path


async def user_lectures(user_id: uuid.UUID) -> list[Lecture]:
    async with SessionLocal() as session:
        rows = await session.scalars(select(Lecture).where(Lecture.owner_id == user_id))
        return list(rows)


async def test_pre_create_without_token_rejected(client):
    response = await client.post(HOOKS_URL, json=hook("pre-create", {}, Size=1000))
    assert response.status_code == 200
    body = response.json()
    assert body["RejectUpload"] is True
    assert body["HTTPResponse"]["StatusCode"] == 401


async def test_pre_create_with_bad_token_rejected(client):
    headers = {"Authorization": "Bearer broken"}
    response = await client.post(HOOKS_URL, json=hook("pre-create", headers, Size=1000))
    assert response.json()["HTTPResponse"]["StatusCode"] == 401


async def test_pre_create_rejects_large_and_deferred(client, auth_headers):
    too_large = hook("pre-create", auth_headers, Size=2 * 1024**3 + 1)
    response = await client.post(HOOKS_URL, json=too_large)
    assert response.json()["HTTPResponse"]["StatusCode"] == 413

    deferred = hook("pre-create", auth_headers, Size=0, SizeIsDeferred=True)
    response = await client.post(HOOKS_URL, json=deferred)
    assert response.json()["HTTPResponse"]["StatusCode"] == 411


async def test_pre_create_rejects_foreign_course(client, auth_headers):
    request = hook("pre-create", auth_headers, Size=1000, MetaData={"course_id": str(uuid.uuid4())})
    response = await client.post(HOOKS_URL, json=request)
    assert response.json()["HTTPResponse"]["StatusCode"] == 404

    request["Event"]["Upload"]["MetaData"]["course_id"] = "not-a-uuid"
    response = await client.post(HOOKS_URL, json=request)
    assert response.json()["HTTPResponse"]["StatusCode"] == 422


async def test_pre_create_binds_upload_to_user(client, user, auth_headers):
    request = hook("pre-create", auth_headers, Size=1000, MetaData={"filename": "a.mp4"})
    response = await client.post(HOOKS_URL, json=request)
    body = response.json()
    assert "RejectUpload" not in body
    upload_id = body["ChangeFileInfo"]["ID"]
    assert uploads_api.UPLOAD_ID.fullmatch(upload_id)
    assert upload_id.startswith(user.id.hex)


async def test_pre_finish_creates_lecture(client, user, auth_headers, storage, enqueued):
    course = await client.post("/api/v1/courses", json={"title": "Физика"}, headers=auth_headers)
    course_id = course.json()["id"]
    upload_id = user.id.hex + "a" * 32
    put_upload(storage, upload_id, sample_audio(storage))

    request = hook(
        "pre-finish",
        auth_headers,
        ID=upload_id,
        MetaData={"filename": "Лекция 3.mp4", "course_id": course_id},
    )
    response = await client.post(HOOKS_URL, json=request)
    assert response.status_code == 200
    answer = response.json()["HTTPResponse"]
    assert answer["StatusCode"] == 200

    [lecture] = await user_lectures(user.id)
    assert json.loads(answer["Body"]) == {"lecture_id": str(lecture.id)}
    assert lecture.title == "Лекция 3"
    assert lecture.source_type == SourceType.upload
    assert lecture.status == LectureStatus.queued
    assert lecture.duration_sec == pytest.approx(2.0, abs=0.2)
    original = storage / "originals" / str(lecture.id)
    assert original.is_file()
    assert lecture.audio_path == str(original)
    assert list((storage / "uploads").iterdir()) == []
    assert enqueued == [lecture.id]

    async with SessionLocal() as session:
        linked = await session.scalar(
            select(course_lectures.c.course_id).where(course_lectures.c.lecture_id == lecture.id)
        )
    assert str(linked) == course_id

    repeated = await client.post(HOOKS_URL, json=request)
    assert repeated.json()["HTTPResponse"]["StatusCode"] == 409
    assert len(await user_lectures(user.id)) == 1


async def test_pre_finish_rejects_text_file(client, user, auth_headers, storage, enqueued):
    upload_id = user.id.hex + "b" * 32
    fake_video = storage / "fake.mp4"
    fake_video.write_text("это не видео, а просто текст\n" * 100)
    path = put_upload(storage, upload_id, fake_video)

    request = hook("pre-finish", auth_headers, ID=upload_id, MetaData={"filename": "fake.mp4"})
    response = await client.post(HOOKS_URL, json=request)
    answer = response.json()["HTTPResponse"]
    assert answer["StatusCode"] == 422
    assert json.loads(answer["Body"])["detail"]

    assert await user_lectures(user.id) == []
    assert not path.exists()
    assert enqueued == []


@pytest.mark.parametrize(("anonymous", "status_code"), [(False, 403), (True, 401)])
async def test_pre_finish_discards_foreign_upload(
    client, user, auth_headers, storage, enqueued, anonymous, status_code
):
    upload_id = uuid.uuid4().hex + "c" * 32
    put_upload(storage, upload_id, sample_audio(storage))

    request = hook("pre-finish", {} if anonymous else auth_headers, ID=upload_id)
    response = await client.post(HOOKS_URL, json=request)

    assert response.json()["HTTPResponse"]["StatusCode"] == status_code
    assert await user_lectures(user.id) == []
    assert list((storage / "uploads").iterdir()) == []
    assert enqueued == []


async def test_pre_finish_keeps_incomplete_upload(client, user, auth_headers, storage):
    upload_id = user.id.hex + "d" * 32
    path = put_upload(storage, upload_id, sample_audio(storage))
    with path.open("ab") as file:
        file.write(b"\0")

    response = await client.post(HOOKS_URL, json=hook("pre-finish", auth_headers, ID=upload_id))

    assert response.json()["HTTPResponse"]["StatusCode"] == 409
    assert await user_lectures(user.id) == []
    assert path.exists()


async def test_hooks_reject_proxied_request(client, auth_headers):
    response = await client.post(
        HOOKS_URL,
        json=hook("pre-create", auth_headers, Size=1000),
        headers={"X-Forwarded-For": "203.0.113.7"},
    )
    assert response.status_code == 404
