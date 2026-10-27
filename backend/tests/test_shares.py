import logging
import uuid
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import (
    Chapter,
    Complaint,
    Lecture,
    LectureStatus,
    SourceType,
    Summary,
    TranscriptSegment,
    User,
)
from app.services import rate_limit


@pytest.fixture
async def verified_user(user):
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        db_user.email_verified_at = datetime.now(UTC)
        await session.commit()
    return user


async def create_lecture(
    owner_id: uuid.UUID,
    title: str = "Пределы",
    lecture_status: LectureStatus = LectureStatus.ready,
) -> uuid.UUID:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=owner_id,
            title=title,
            status=lecture_status,
            source_type=SourceType.upload,
            processed_locally=True,
            video_path="/data/video.mp4",
            segments=[TranscriptSegment(idx=0, start=0, end=5, text="Привет")],
            chapters=[Chapter(idx=0, start=0, end=5, title="Введение", summary="Кратко")],
            summary=Summary(content_md="Конспект"),
        )
        session.add(lecture)
        await session.commit()
        return lecture.id


async def create_share(client, headers, **body):
    return await client.post("/api/v1/shares", json=body, headers=headers)


async def test_share_requires_confirmed_account(client, user, auth_headers):
    lecture_id = await create_lecture(user.id)
    response = await create_share(client, auth_headers, lecture_id=str(lecture_id))
    assert response.status_code == 403


async def test_share_with_telegram(client, user, auth_headers):
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        db_user.telegram_chat_id = 12345
        await session.commit()
    lecture_id = await create_lecture(user.id)
    response = await create_share(client, auth_headers, lecture_id=str(lecture_id))
    assert response.status_code == 201


async def test_share_lecture_lifecycle(client, verified_user, auth_headers):
    lecture_id = await create_lecture(verified_user.id)
    created = await create_share(client, auth_headers, lecture_id=str(lecture_id))
    assert created.status_code == 201
    share = created.json()
    assert share["url"].endswith(f"/s/{share['token']}")
    assert share["lecture_id"] == str(lecture_id)
    assert share["revoked_at"] is None

    listed = await client.get("/api/v1/shares", headers=auth_headers)
    assert [item["token"] for item in listed.json()] == [share["token"]]

    public = await client.get(f"/api/v1/public/{share['token']}")
    assert public.status_code == 200
    lecture = public.json()["lecture"]
    assert public.json()["course"] is None
    assert lecture["title"] == "Пределы"
    assert lecture["processed_locally"] is True
    assert lecture["video_url"] == f"/media/{lecture_id}.mp4"
    assert lecture["segments"][0]["text"] == "Привет"
    assert lecture["chapters"][0]["title"] == "Введение"
    assert lecture["summary"]["content_md"] == "Конспект"
    assert "owner_id" not in lecture
    assert "status" not in lecture

    revoked = await client.delete(f"/api/v1/shares/{share['token']}", headers=auth_headers)
    assert revoked.status_code == 204
    assert (await client.get(f"/api/v1/public/{share['token']}")).status_code == 404
    assert (await client.get("/api/v1/shares", headers=auth_headers)).json() == []
    again = await client.delete(f"/api/v1/shares/{share['token']}", headers=auth_headers)
    assert again.status_code == 404


async def test_share_course(client, verified_user, auth_headers):
    first = await create_lecture(verified_user.id, "Пределы")
    second = await create_lecture(verified_user.id, "Ряды")
    course = (
        await client.post("/api/v1/courses", json={"title": "Матан"}, headers=auth_headers)
    ).json()
    for lecture_id in (first, second):
        await client.post(
            f"/api/v1/courses/{course['id']}/lectures",
            json={"lecture_id": str(lecture_id)},
            headers=auth_headers,
        )
    lecture_share = (await create_share(client, auth_headers, lecture_id=str(first))).json()
    course_share = (await create_share(client, auth_headers, course_id=course["id"])).json()

    public = await client.get(f"/api/v1/public/{course_share['token']}")
    assert public.status_code == 200
    body = public.json()
    assert body["lecture"] is None
    assert body["course"]["title"] == "Матан"
    assert [item["title"] for item in body["course"]["lectures"]] == ["Пределы", "Ряды"]
    assert [item["share_token"] for item in body["course"]["lectures"]] == [
        lecture_share["token"],
        None,
    ]
    assert all(item["processed_locally"] for item in body["course"]["lectures"])


async def test_share_validation(client, verified_user, auth_headers):
    lecture_id = await create_lecture(verified_user.id)
    assert (await create_share(client, auth_headers)).status_code == 422
    both = await create_share(
        client, auth_headers, lecture_id=str(lecture_id), course_id=str(uuid.uuid4())
    )
    assert both.status_code == 422
    missing = await create_share(client, auth_headers, lecture_id=str(uuid.uuid4()))
    assert missing.status_code == 404


async def test_cannot_share_or_revoke_foreign(client, verified_user, auth_headers):
    async with SessionLocal() as session:
        other = User(display_name="Другой", email_verified_at=datetime.now(UTC))
        session.add(other)
        await session.commit()
        other_id = other.id
    try:
        other_headers = {"Authorization": f"Bearer {create_access_token(other_id)}"}
        lecture_id = await create_lecture(verified_user.id)
        assert (
            await create_share(client, other_headers, lecture_id=str(lecture_id))
        ).status_code == 404
        share = (await create_share(client, auth_headers, lecture_id=str(lecture_id))).json()
        revoke = await client.delete(f"/api/v1/shares/{share['token']}", headers=other_headers)
        assert revoke.status_code == 404
        assert (await client.get(f"/api/v1/public/{share['token']}")).status_code == 200
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, other_id))
            await session.commit()


async def test_unknown_token_is_404(client):
    assert (await client.get("/api/v1/public/nope")).status_code == 404


async def test_shares_require_auth(client):
    assert (await client.get("/api/v1/shares")).status_code == 401


async def test_revoked_course_share_is_404(client, verified_user, auth_headers):
    course = (
        await client.post("/api/v1/courses", json={"title": "Матан"}, headers=auth_headers)
    ).json()
    share = (await create_share(client, auth_headers, course_id=course["id"])).json()
    assert (await client.get(f"/api/v1/public/{share['token']}")).status_code == 200
    revoked = await client.delete(f"/api/v1/shares/{share['token']}", headers=auth_headers)
    assert revoked.status_code == 204
    assert (await client.get(f"/api/v1/public/{share['token']}")).status_code == 404


@pytest.mark.parametrize(
    "lecture_status",
    [
        LectureStatus.queued,
        LectureStatus.waiting_quota,
        LectureStatus.processing,
        LectureStatus.failed,
    ],
)
async def test_cannot_share_unready_lecture(client, verified_user, auth_headers, lecture_status):
    lecture_id = await create_lecture(verified_user.id, lecture_status=lecture_status)
    response = await create_share(client, auth_headers, lecture_id=str(lecture_id))
    assert response.status_code == 409


async def test_public_course_hides_unready_lectures(client, verified_user, auth_headers):
    ready = await create_lecture(verified_user.id, "Пределы")
    failed = await create_lecture(verified_user.id, "Ряды", LectureStatus.failed)
    course = (
        await client.post("/api/v1/courses", json={"title": "Матан"}, headers=auth_headers)
    ).json()
    for lecture_id in (ready, failed):
        await client.post(
            f"/api/v1/courses/{course['id']}/lectures",
            json={"lecture_id": str(lecture_id)},
            headers=auth_headers,
        )
    share = (await create_share(client, auth_headers, course_id=course["id"])).json()
    public = await client.get(f"/api/v1/public/{share['token']}")
    assert [item["title"] for item in public.json()["course"]["lectures"]] == ["Пределы"]


async def test_public_lecture_hidden_after_leaving_ready(client, verified_user, auth_headers):
    lecture_id = await create_lecture(verified_user.id)
    share = (await create_share(client, auth_headers, lecture_id=str(lecture_id))).json()
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, lecture_id)
        lecture.status = LectureStatus.processing
        await session.commit()
    assert (await client.get(f"/api/v1/public/{share['token']}")).status_code == 404


@pytest.fixture
async def complaint_share(client, verified_user, auth_headers, reset_complaint_limit):
    lecture_id = await create_lecture(verified_user.id)
    share = (await create_share(client, auth_headers, lecture_id=str(lecture_id))).json()
    return share


@pytest.fixture
async def reset_complaint_limit():
    redis = Redis.from_url(get_settings().redis_url)
    await redis.delete("rate:complaints:ip:127.0.0.1")
    yield
    await redis.delete("rate:complaints:ip:127.0.0.1")
    await redis.aclose()


async def test_complaint_saved_and_logged(client, complaint_share, verified_user, caplog):
    with caplog.at_level(logging.WARNING, logger="app.api.shares"):
        response = await client.post(
            f"/api/v1/public/{complaint_share['token']}/complaints",
            json={"reason": "  Нарушение прав  "},
        )
    assert response.status_code == 204
    assert response.content == b""
    async with SessionLocal() as session:
        complaint = await session.scalar(
            select(Complaint).where(Complaint.lecture_id == complaint_share["lecture_id"])
        )
        assert complaint.reason == "Нарушение прав"
        assert complaint.reporter_id is None
        assert str(complaint.id) in caplog.text
    assert str(verified_user.id) in caplog.text
    assert complaint_share["token"] not in caplog.text
    assert "Нарушение прав" not in caplog.text


async def test_complaint_limit_ignores_forwarded_headers(client, complaint_share, monkeypatch):
    monkeypatch.setattr(get_settings(), "complaints_rate_limit", 2)
    url = f"/api/v1/public/{complaint_share['token']}/complaints"
    for index in range(2):
        response = await client.post(
            url,
            json={"reason": "Нарушение"},
            headers={"X-Forwarded-For": f"192.0.2.{index}", "X-Real-IP": f"192.0.2.{index}"},
        )
        assert response.status_code == 204
    assert (await client.post(url, json={"reason": "Нарушение"})).status_code == 429
    assert (
        await client.post("/api/v1/public/unknown/complaints", json={"reason": "Нарушение"})
    ).status_code == 429


async def test_complaint_redis_failure_is_closed(client, complaint_share, monkeypatch):
    async def unavailable(*args):
        raise OSError("unavailable")

    monkeypatch.setattr(rate_limit, "is_rate_limited", unavailable)
    response = await client.post(
        f"/api/v1/public/{complaint_share['token']}/complaints", json={"reason": "Нарушение"}
    )
    assert response.status_code == 503
    async with SessionLocal() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Complaint)
                .where(Complaint.lecture_id == complaint_share["lecture_id"])
            )
            == 0
        )


@pytest.mark.parametrize("reason", ["", "   ", "я" * 5001])
async def test_complaint_reason_validation(client, complaint_share, reason):
    response = await client.post(
        f"/api/v1/public/{complaint_share['token']}/complaints", json={"reason": reason}
    )
    assert response.status_code == 422


async def test_complaint_unknown_and_revoked(client, complaint_share, auth_headers):
    assert (
        await client.post("/api/v1/public/unknown/complaints", json={"reason": "Нарушение"})
    ).status_code == 404
    await client.delete(f"/api/v1/shares/{complaint_share['token']}", headers=auth_headers)
    assert (
        await client.post(
            f"/api/v1/public/{complaint_share['token']}/complaints", json={"reason": "Нарушение"}
        )
    ).status_code == 404


async def test_complaint_unready_lecture(client, complaint_share):
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, uuid.UUID(complaint_share["lecture_id"]))
        lecture.status = LectureStatus.failed
        await session.commit()
    assert (
        await client.post(
            f"/api/v1/public/{complaint_share['token']}/complaints", json={"reason": "Нарушение"}
        )
    ).status_code == 404


async def test_complaint_course_requires_lecture(
    client, verified_user, auth_headers, reset_complaint_limit
):
    course = (
        await client.post("/api/v1/courses", json={"title": "Матан"}, headers=auth_headers)
    ).json()
    share = (await create_share(client, auth_headers, course_id=course["id"])).json()
    assert (
        await client.post(
            f"/api/v1/public/{share['token']}/complaints", json={"reason": "Нарушение"}
        )
    ).status_code == 422
