import uuid
from datetime import UTC, datetime

import pytest

from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import Chapter, Lecture, SourceType, Summary, TranscriptSegment, User


@pytest.fixture
async def verified_user(user):
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        db_user.email_verified_at = datetime.now(UTC)
        await session.commit()
    return user


async def create_lecture(owner_id: uuid.UUID, title: str = "Пределы") -> uuid.UUID:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=owner_id,
            title=title,
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
