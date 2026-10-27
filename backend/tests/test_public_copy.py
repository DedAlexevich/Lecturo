import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import (
    ALGORITHM,
    PUBLIC_EXPORT_SCOPE,
    create_access_token,
    create_export_token,
    create_public_export_token,
)
from app.models import (
    Chapter,
    Course,
    Lecture,
    LectureStatus,
    SearchChunk,
    ShareLink,
    SourceType,
    Summary,
    TranscriptSegment,
    UsageEntry,
    User,
    course_lectures,
)
from app.models.base import EMBEDDING_DIM
from app.models.search import ChunkKind
from app.services.rate_limit import reset_rate_limit


@pytest.fixture(autouse=True)
async def fresh_export_limit() -> None:
    await reset_rate_limit(get_settings().redis_url, "rate:public-export:ip:127.0.0.1")


@pytest.fixture
async def visitor(user) -> User:
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        db_user.email_verified_at = datetime.now(UTC)
        db_user.personal_data_accepted_at = datetime.now(UTC)
        await session.commit()
    return user


@pytest.fixture
async def owner() -> AsyncIterator[User]:
    async with SessionLocal() as session:
        owner = User(
            display_name="Автор",
            email_verified_at=datetime.now(UTC),
            personal_data_accepted_at=datetime.now(UTC),
        )
        session.add(owner)
        await session.commit()
        yield owner
        await session.delete(owner)
        await session.commit()


def embedding(value: float) -> list[float]:
    return [value] * EMBEDDING_DIM


async def create_source(
    owner_id: uuid.UUID,
    title: str = "Пределы",
    source_type: SourceType = SourceType.upload,
    lecture_status: LectureStatus = LectureStatus.ready,
) -> uuid.UUID:
    is_link = source_type == SourceType.link
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=owner_id,
            title=title,
            status=lecture_status,
            source_type=source_type,
            source_url="https://youtu.be/abc" if is_link else None,
            embed_url="https://www.youtube.com/embed/abc" if is_link else None,
            duration_sec=120.5,
            language="ru",
            processed_locally=True,
            video_path=None if is_link else "/data/video.mp4",
            audio_path=None if is_link else "/data/audio.opus",
            video_expires_at=None if is_link else datetime.now(UTC) + timedelta(days=3),
            segments=[
                TranscriptSegment(idx=0, start=0, end=5, text="Привет"),
                TranscriptSegment(idx=1, start=5, end=9, text="Мир"),
            ],
            chapters=[Chapter(idx=0, start=0, end=9, title="Введение", summary="Кратко")],
            summary=Summary(content_md="## Конспект\n\nТекст"),
        )
        session.add(lecture)
        await session.flush()
        session.add_all(
            [
                SearchChunk(
                    lecture_id=lecture.id,
                    kind=ChunkKind.transcript,
                    start=0,
                    end=5,
                    section=0,
                    text="Привет",
                    embedding=embedding(0.25),
                ),
                SearchChunk(
                    lecture_id=lecture.id,
                    kind=ChunkKind.summary,
                    section=1,
                    text="Конспект",
                    embedding=embedding(0.5),
                ),
            ]
        )
        await session.commit()
        return lecture.id


async def create_share(owner_id: uuid.UUID, **target) -> str:
    token = uuid.uuid4().hex
    async with SessionLocal() as session:
        session.add(ShareLink(token=token, owner_id=owner_id, **target))
        await session.commit()
    return token


async def revoke(token: str) -> None:
    async with SessionLocal() as session:
        share = await session.scalar(select(ShareLink).where(ShareLink.token == token))
        share.revoked_at = datetime.now(UTC)
        await session.commit()


async def create_course(owner_id: uuid.UUID, lecture_ids: list[uuid.UUID]) -> uuid.UUID:
    async with SessionLocal() as session:
        course = Course(owner_id=owner_id, title="Матан", description="Первый семестр")
        session.add(course)
        await session.flush()
        for position, lecture_id in enumerate(lecture_ids):
            await session.execute(
                course_lectures.insert().values(
                    course_id=course.id, lecture_id=lecture_id, position=position
                )
            )
        await session.commit()
        return course.id


def copy_url(token: str) -> str:
    return f"/api/v1/public/{token}/copy"


async def lectures_of(owner_id: uuid.UUID) -> list[Lecture]:
    async with SessionLocal() as session:
        return list(await session.scalars(select(Lecture).where(Lecture.owner_id == owner_id)))


async def test_copy_uploaded_lecture(client, visitor, owner, auth_headers):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)

    response = await client.post(copy_url(token), headers=auth_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["course_id"] is None
    copy_id = uuid.UUID(body["lecture_id"])
    assert body["lecture_ids"] == [str(copy_id)]
    assert copy_id != source_id

    async with SessionLocal() as session:
        copy = await session.get(Lecture, copy_id)
        assert copy.owner_id == visitor.id
        assert copy.status == LectureStatus.ready
        assert copy.title == "Пределы"
        assert copy.source_type == SourceType.upload
        assert copy.source_url is None
        assert copy.embed_url is None
        assert copy.video_path is None
        assert copy.audio_path is None
        assert copy.video_expires_at is None
        assert copy.duration_sec == 120.5
        assert copy.processed_locally is True
        segments = (
            await session.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.lecture_id == copy_id)
                .order_by(TranscriptSegment.idx)
            )
        ).all()
        assert [(s.idx, s.start, s.end, s.text) for s in segments] == [
            (0, 0, 5, "Привет"),
            (1, 5, 9, "Мир"),
        ]
        chapters = (
            await session.scalars(select(Chapter).where(Chapter.lecture_id == copy_id))
        ).all()
        assert [(c.title, c.summary) for c in chapters] == [("Введение", "Кратко")]
        summary = await session.get(Summary, copy_id)
        assert summary.content_md == "## Конспект\n\nТекст"
        chunks = (
            await session.scalars(
                select(SearchChunk)
                .where(SearchChunk.lecture_id == copy_id)
                .order_by(SearchChunk.kind)
            )
        ).all()
        assert [(c.kind, c.text, c.section) for c in chunks] == [
            (ChunkKind.transcript, "Привет", 0),
            (ChunkKind.summary, "Конспект", 1),
        ]
        assert list(chunks[0].embedding) == pytest.approx(embedding(0.25))
        assert list(chunks[1].embedding) == pytest.approx(embedding(0.5))
        usage = await session.scalar(
            select(func.count()).select_from(UsageEntry).where(UsageEntry.user_id == visitor.id)
        )
        assert usage == 0
        original = await session.get(Lecture, source_id)
        assert original.owner_id == owner.id
        assert original.video_path == "/data/video.mp4"

    detail = await client.get(f"/api/v1/lectures/{copy_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "ready"
    assert "copied_from_id" not in detail.json()
    assert [lecture.id for lecture in await lectures_of(owner.id)] == [source_id]


async def test_copy_link_lecture_keeps_source(client, visitor, owner, auth_headers):
    source_id = await create_source(owner.id, source_type=SourceType.link)
    token = await create_share(owner.id, lecture_id=source_id)

    response = await client.post(copy_url(token), headers=auth_headers)

    assert response.status_code == 201
    async with SessionLocal() as session:
        copy = await session.get(Lecture, uuid.UUID(response.json()["lecture_id"]))
        assert copy.source_type == SourceType.link
        assert copy.source_url == "https://youtu.be/abc"
        assert copy.embed_url == "https://www.youtube.com/embed/abc"
        assert copy.video_path is None


async def test_copy_is_unlinked_from_share(client, visitor, owner, auth_headers):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)
    copy_id = (await client.post(copy_url(token), headers=auth_headers)).json()["lecture_id"]

    await revoke(token)

    still_there = await client.get(f"/api/v1/lectures/{copy_id}", headers=auth_headers)
    assert still_there.status_code == 200
    async with SessionLocal() as session:
        shares = await session.scalar(
            select(func.count())
            .select_from(ShareLink)
            .where(ShareLink.lecture_id == uuid.UUID(copy_id))
        )
        assert shares == 0


async def test_repeat_returns_existing(client, visitor, owner, auth_headers):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)

    first = await client.post(copy_url(token), headers=auth_headers)
    second = await client.post(copy_url(token), headers=auth_headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["lecture_id"] == first.json()["lecture_id"]
    assert second.json()["created"] is False
    assert len(await lectures_of(visitor.id)) == 1


async def test_repeat_does_not_use_limit(client, visitor, owner, auth_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_copy_daily_limit", 1)
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)

    assert (await client.post(copy_url(token), headers=auth_headers)).status_code == 201
    assert (await client.post(copy_url(token), headers=auth_headers)).status_code == 200


async def test_own_lecture_conflict(client, owner):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)
    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}

    response = await client.post(copy_url(token), headers=headers)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["lecture_id"] == str(source_id)
    assert detail["message"]
    assert len(await lectures_of(owner.id)) == 1


async def test_daily_limit(client, visitor, owner, auth_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_copy_daily_limit", 2)
    tokens = [
        await create_share(owner.id, lecture_id=await create_source(owner.id, f"Лекция {n}"))
        for n in range(3)
    ]

    statuses = [(await client.post(copy_url(t), headers=auth_headers)).status_code for t in tokens]

    assert statuses == [201, 201, 429]
    assert len(await lectures_of(visitor.id)) == 2


async def test_failed_copy_does_not_spend_limit(client, visitor, owner, auth_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_copy_daily_limit", 1)
    token = await create_share(owner.id, lecture_id=await create_source(owner.id))

    async def broken(*args, **kwargs):
        raise RuntimeError("сбой записи")

    monkeypatch.setattr("app.api.public_copy.copy_lecture", broken)
    with pytest.raises(RuntimeError):
        await client.post(copy_url(token), headers=auth_headers)
    monkeypatch.undo()
    monkeypatch.setattr(get_settings(), "public_copy_daily_limit", 1)

    assert (await client.post(copy_url(token), headers=auth_headers)).status_code == 201
    assert len(await lectures_of(visitor.id)) == 1


async def test_revoked_link(client, visitor, owner, auth_headers):
    token = await create_share(owner.id, lecture_id=await create_source(owner.id))
    await revoke(token)

    response = await client.post(copy_url(token), headers=auth_headers)

    assert response.status_code == 404
    assert await lectures_of(visitor.id) == []


async def test_unknown_link(client, visitor, auth_headers):
    response = await client.post(copy_url("net-takoy-ssylki"), headers=auth_headers)
    assert response.status_code == 404


async def test_lecture_not_ready(client, visitor, owner, auth_headers):
    source_id = await create_source(owner.id, lecture_status=LectureStatus.processing)
    token = await create_share(owner.id, lecture_id=source_id)

    response = await client.post(copy_url(token), headers=auth_headers)

    assert response.status_code == 404
    assert await lectures_of(visitor.id) == []


async def test_requires_login(client, owner):
    token = await create_share(owner.id, lecture_id=await create_source(owner.id))
    assert (await client.post(copy_url(token))).status_code == 401


async def test_requires_confirmed_account(client, user, owner, auth_headers):
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        db_user.personal_data_accepted_at = datetime.now(UTC)
        await session.commit()
    token = await create_share(owner.id, lecture_id=await create_source(owner.id))

    response = await client.post(copy_url(token), headers=auth_headers)

    assert response.status_code == 403
    assert await lectures_of(user.id) == []


async def test_requires_personal_data_consent(client, user, owner, auth_headers):
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        db_user.email_verified_at = datetime.now(UTC)
        await session.commit()
    token = await create_share(owner.id, lecture_id=await create_source(owner.id))

    response = await client.post(copy_url(token), headers=auth_headers)

    assert response.status_code == 403
    assert await lectures_of(user.id) == []


async def test_copy_whole_course(client, visitor, owner, auth_headers):
    ready = await create_source(owner.id, "Первая")
    other = await create_source(owner.id, "Вторая", source_type=SourceType.link)
    hidden = await create_source(owner.id, "Черновик", lecture_status=LectureStatus.failed)
    course_id = await create_course(owner.id, [ready, other, hidden])
    token = await create_share(owner.id, course_id=course_id)

    response = await client.post(copy_url(token), headers=auth_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["lecture_id"] is None
    assert len(body["lecture_ids"]) == 2
    async with SessionLocal() as session:
        copy = await session.get(Course, uuid.UUID(body["course_id"]))
        assert copy.owner_id == visitor.id
        assert (copy.title, copy.description) == ("Матан", "Первый семестр")
        rows = (
            await session.execute(
                select(course_lectures.c.lecture_id, course_lectures.c.position)
                .where(course_lectures.c.course_id == copy.id)
                .order_by(course_lectures.c.position)
            )
        ).all()
        assert [str(row.lecture_id) for row in rows] == body["lecture_ids"]
        titles = [(await session.get(Lecture, row.lecture_id)).title for row in rows]
        assert titles == ["Первая", "Вторая"]

    repeat = await client.post(copy_url(token), headers=auth_headers)
    assert repeat.status_code == 200
    assert repeat.json()["course_id"] == body["course_id"]
    assert repeat.json()["lecture_ids"] == body["lecture_ids"]
    assert len(await lectures_of(visitor.id)) == 2


async def test_course_copy_reuses_saved_lecture(client, visitor, owner, auth_headers):
    first = await create_source(owner.id, "Первая")
    second = await create_source(owner.id, "Вторая")
    course_id = await create_course(owner.id, [first, second])
    token = await create_share(owner.id, course_id=course_id)
    single = await client.post(
        copy_url(token), json={"lecture_id": str(first)}, headers=auth_headers
    )
    assert single.status_code == 201
    assert single.json()["course_id"] is None

    whole = await client.post(copy_url(token), headers=auth_headers)

    assert whole.status_code == 201
    assert single.json()["lecture_id"] in whole.json()["lecture_ids"]
    assert len(await lectures_of(visitor.id)) == 2


async def test_course_limit_counts_lectures(client, visitor, owner, auth_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_copy_daily_limit", 2)
    lecture_ids = [await create_source(owner.id, f"Лекция {n}") for n in range(3)]
    token = await create_share(owner.id, course_id=await create_course(owner.id, lecture_ids))

    response = await client.post(copy_url(token), headers=auth_headers)

    assert response.status_code == 429
    assert await lectures_of(visitor.id) == []


async def test_lecture_outside_course_is_not_copied(client, visitor, owner, auth_headers):
    inside = await create_source(owner.id, "Внутри")
    outside = await create_source(owner.id, "Снаружи")
    token = await create_share(owner.id, course_id=await create_course(owner.id, [inside]))

    response = await client.post(
        copy_url(token), json={"lecture_id": str(outside)}, headers=auth_headers
    )

    assert response.status_code == 404
    assert await lectures_of(visitor.id) == []


async def test_own_course_conflict(client, owner):
    course_id = await create_course(owner.id, [await create_source(owner.id)])
    token = await create_share(owner.id, course_id=course_id)
    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}

    response = await client.post(copy_url(token), headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["course_id"] == str(course_id)


async def test_deleting_copy_keeps_original(client, visitor, owner, auth_headers):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)
    copy_id = (await client.post(copy_url(token), headers=auth_headers)).json()["lecture_id"]

    deleted = await client.delete(f"/api/v1/lectures/{copy_id}", headers=auth_headers)

    assert deleted.status_code == 204
    public = await client.get(f"/api/v1/public/{token}")
    assert public.status_code == 200
    assert len(public.json()["lecture"]["segments"]) == 2


def link_url(token: str, lecture_id: uuid.UUID, export_format: str) -> str:
    return f"/api/v1/public/{token}/lectures/{lecture_id}/exports/{export_format}/link"


def grant_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["grant"][0]


@pytest.mark.parametrize(
    ("export_format", "needle", "media_type"),
    [
        ("md", "## Конспект", "text/markdown"),
        ("srt", "Привет", "application/x-subrip"),
        ("vtt", "WEBVTT", "text/vtt"),
    ],
)
async def test_public_export_without_account(client, owner, export_format, needle, media_type):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)

    link = await client.post(link_url(token, source_id, export_format))

    assert link.status_code == 200
    body = link.json()
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert timedelta(0) < expires_at - datetime.now(UTC) <= timedelta(minutes=2)
    assert (
        urlsplit(body["url"]).path
        == f"/api/v1/public/{token}/lectures/{source_id}/export.{export_format}"
    )
    file = await client.get(body["url"])
    assert file.status_code == 200
    assert file.headers["content-type"].startswith(media_type)
    assert file.headers["cache-control"] == "no-store"
    assert "attachment" in file.headers["content-disposition"]
    assert needle in file.text


async def test_public_markdown_has_title(client, owner):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)
    link = await client.post(link_url(token, source_id, "md"))

    file = await client.get(link.json()["url"])

    assert file.text == "# Пределы\n\n## Конспект\n\nТекст\n"


async def test_public_export_pdf(client, owner):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)

    link = await client.post(link_url(token, source_id, "pdf"))
    assert link.status_code == 200
    file = await client.get(link.json()["url"])

    assert file.status_code == 200
    assert file.content.startswith(b"%PDF")


async def test_public_export_course_lecture(client, owner):
    inside = await create_source(owner.id, "Внутри")
    outside = await create_source(owner.id, "Снаружи")
    token = await create_share(owner.id, course_id=await create_course(owner.id, [inside]))

    allowed = await client.post(link_url(token, inside, "md"))
    denied = await client.post(link_url(token, outside, "md"))

    assert allowed.status_code == 200
    assert denied.status_code == 404


async def test_public_export_revoked_link(client, owner):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)
    link = await client.post(link_url(token, source_id, "md"))
    await revoke(token)

    assert (await client.get(link.json()["url"])).status_code == 404
    assert (await client.post(link_url(token, source_id, "md"))).status_code == 404
    assert (await client.post(link_url(token, source_id, "pdf"))).status_code == 404


async def test_public_export_not_ready(client, owner):
    source_id = await create_source(owner.id, lecture_status=LectureStatus.processing)
    token = await create_share(owner.id, lecture_id=source_id)

    assert (await client.post(link_url(token, source_id, "md"))).status_code == 404


async def test_public_export_needs_grant(client, owner):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)
    path = f"/api/v1/public/{token}/lectures/{source_id}/export.md"

    assert (await client.get(path)).status_code == 422
    assert (await client.get(path, params={"grant": "мусор"})).status_code == 401


async def test_public_grant_is_bound_to_file(client, owner):
    source_id = await create_source(owner.id)
    other_id = await create_source(owner.id, "Другая")
    token = await create_share(owner.id, lecture_id=source_id)
    other_token = await create_share(owner.id, lecture_id=other_id)
    grant = grant_of((await client.post(link_url(token, source_id, "md"))).json()["url"])
    base = f"/api/v1/public/{token}/lectures/{source_id}"

    assert (await client.get(f"{base}/export.vtt", params={"grant": grant})).status_code == 403
    other_path = f"/api/v1/public/{other_token}/lectures/{source_id}/export.md"
    assert (await client.get(other_path, params={"grant": grant})).status_code == 403
    other_lecture = f"/api/v1/public/{token}/lectures/{other_id}/export.md"
    assert (await client.get(other_lecture, params={"grant": grant})).status_code == 403
    assert (await client.get(f"{base}/export.md", params={"grant": grant})).status_code == 200


async def test_public_grant_expires(client, owner):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)
    expired = jwt.encode(
        {
            "sub": token,
            "aud": PUBLIC_EXPORT_SCOPE,
            "scope": PUBLIC_EXPORT_SCOPE,
            "lecture_id": str(source_id),
            "format": "md",
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        },
        get_settings().secret_key,
        algorithm=ALGORITHM,
    )

    response = await client.get(
        f"/api/v1/public/{token}/lectures/{source_id}/export.md", params={"grant": expired}
    )

    assert response.status_code == 401


async def test_private_export_token_is_not_a_public_grant(client, owner):
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)
    private_token, _ = create_export_token(owner.id, source_id, "srt")

    response = await client.get(
        f"/api/v1/public/{token}/lectures/{source_id}/export.srt", params={"grant": private_token}
    )

    assert response.status_code == 401


async def test_public_grant_is_not_a_private_export_token(client, owner, visitor, auth_headers):
    source_id = await create_source(owner.id)
    grant, _ = create_public_export_token("x", source_id, "srt")

    response = await client.get(f"/api/v1/lectures/{source_id}/export.srt", params={"token": grant})

    assert response.status_code == 401


async def test_public_export_rate_limit(client, owner, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "public_export_rate_limit", 1)
    monkeypatch.setattr(settings, "public_export_rate_window_seconds", 60)
    source_id = await create_source(owner.id)
    token = await create_share(owner.id, lecture_id=source_id)

    first = await client.post(link_url(token, source_id, "md"))
    second = await client.post(link_url(token, source_id, "md"))

    assert first.status_code == 200
    assert second.status_code == 429
