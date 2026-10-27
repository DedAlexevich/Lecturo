import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import ALGORITHM, create_access_token, create_export_token
from app.models import Lecture, SourceType, TranscriptSegment, User


@pytest.fixture
async def stranger() -> AsyncIterator[User]:
    async with SessionLocal() as session:
        stranger = User(display_name="Чужой")
        session.add(stranger)
        await session.commit()
        yield stranger
        await session.delete(stranger)
        await session.commit()


async def create_lecture(owner: User, texts: list[str]) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=owner.id, title="Матанализ", source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        session.add_all(
            TranscriptSegment(lecture_id=lecture.id, idx=idx, start=idx, end=idx + 1, text=text)
            for idx, text in enumerate(texts)
        )
        await session.commit()
        return lecture


async def request_link(client, headers, lecture_id, export_format):
    return await client.post(
        f"/api/v1/lectures/{lecture_id}/exports/{export_format}/link", headers=headers
    )


def token_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["token"][0]


@pytest.mark.parametrize("export_format", ["srt", "vtt"])
async def test_link_downloads_without_header(client, user, auth_headers, export_format):
    lecture = await create_lecture(user, ["раз", "два"])

    link = await request_link(client, auth_headers, lecture.id, export_format)

    assert link.status_code == 200
    body = link.json()
    assert urlsplit(body["url"]).path == f"/api/v1/lectures/{lecture.id}/export.{export_format}"
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert timedelta(0) < expires_at - datetime.now(UTC) <= timedelta(minutes=2)

    response = await client.get(body["url"])
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "раз" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_pdf_link_needs_summary(client, user, auth_headers):
    lecture = await create_lecture(user, ["раз"])

    response = await request_link(client, auth_headers, lecture.id, "pdf")

    assert response.status_code == 409


async def test_link_requires_auth(client, user):
    lecture = await create_lecture(user, ["раз"])

    response = await request_link(client, {}, lecture.id, "srt")

    assert response.status_code == 401


async def test_link_for_foreign_or_missing_lecture(client, auth_headers, stranger):
    lecture = await create_lecture(stranger, ["чужое"])

    foreign = await request_link(client, auth_headers, lecture.id, "srt")
    missing = await request_link(client, auth_headers, uuid.uuid4(), "srt")

    assert foreign.status_code == 404
    assert missing.status_code == 404


async def test_link_without_transcript(client, user, auth_headers):
    lecture = await create_lecture(user, [])

    response = await request_link(client, auth_headers, lecture.id, "srt")

    assert response.status_code == 409


async def test_link_unknown_format(client, user, auth_headers):
    lecture = await create_lecture(user, ["раз"])

    response = await request_link(client, auth_headers, lecture.id, "docx")

    assert response.status_code == 422


async def test_token_is_bound_to_format(client, user, auth_headers):
    lecture = await create_lecture(user, ["раз"])
    link = (await request_link(client, auth_headers, lecture.id, "srt")).json()

    response = await client.get(
        f"/api/v1/lectures/{lecture.id}/export.vtt", params={"token": token_of(link["url"])}
    )

    assert response.status_code == 403


async def test_token_is_bound_to_lecture(client, user, auth_headers):
    first = await create_lecture(user, ["раз"])
    second = await create_lecture(user, ["два"])
    link = (await request_link(client, auth_headers, first.id, "srt")).json()

    response = await client.get(
        f"/api/v1/lectures/{second.id}/export.srt", params={"token": token_of(link["url"])}
    )

    assert response.status_code == 403


async def test_token_of_another_user_hides_lecture(client, user, stranger):
    lecture = await create_lecture(user, ["раз"])
    token, _ = create_export_token(stranger.id, lecture.id, "srt")

    response = await client.get(
        f"/api/v1/lectures/{lecture.id}/export.srt", params={"token": token}
    )

    assert response.status_code == 404


async def test_expired_token(client, user):
    lecture = await create_lecture(user, ["раз"])
    token = jwt.encode(
        {
            "sub": str(user.id),
            "aud": "export",
            "scope": "export",
            "lecture_id": str(lecture.id),
            "format": "srt",
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        },
        get_settings().secret_key,
        algorithm=ALGORITHM,
    )

    response = await client.get(
        f"/api/v1/lectures/{lecture.id}/export.srt", params={"token": token}
    )

    assert response.status_code == 401


async def test_forged_token(client, user):
    lecture = await create_lecture(user, ["раз"])
    token, _ = create_export_token(user.id, lecture.id, "srt")
    forged = jwt.encode(
        jwt.decode(token, options={"verify_signature": False}),
        "другой ключ подписи для проверки ссылок",
        algorithm=ALGORITHM,
    )

    response = await client.get(
        f"/api/v1/lectures/{lecture.id}/export.srt", params={"token": forged}
    )

    assert response.status_code == 401


async def test_access_token_is_not_accepted_in_query(client, user):
    lecture = await create_lecture(user, ["раз"])

    response = await client.get(
        f"/api/v1/lectures/{lecture.id}/export.srt",
        params={"token": create_access_token(user.id)},
    )

    assert response.status_code == 401


async def test_export_token_is_not_an_access_token(client, user):
    lecture = await create_lecture(user, ["раз"])
    token, _ = create_export_token(user.id, lecture.id, "srt")
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/me", headers=headers)
    export = await client.get(f"/api/v1/lectures/{lecture.id}/export.srt", headers=headers)

    assert me.status_code == 401
    assert export.status_code == 401
