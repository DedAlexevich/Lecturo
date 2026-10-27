import time
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import update

from app.core.db import SessionLocal
from app.models import Lecture, LectureStatus, ShareLink, SourceType
from app.pipeline import video_access
from app.pipeline.video_access import signed_video_url, video_signature


async def create_lecture(owner_id: uuid.UUID, video_path: str | None = "/data/video.mp4"):
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=owner_id,
            title="Пределы",
            status=LectureStatus.ready,
            source_type=SourceType.upload,
            video_path=video_path,
        )
        session.add(lecture)
        await session.commit()
        return lecture.id


async def create_share(owner_id: uuid.UUID, lecture_id: uuid.UUID, token: str) -> None:
    async with SessionLocal() as session:
        session.add(ShareLink(token=token, owner_id=owner_id, lecture_id=lecture_id))
        await session.commit()


def access_path(video_url: str) -> str:
    parts = urlsplit(video_url)
    lecture_id = parts.path.removeprefix("/media/").removesuffix(".mp4")
    return f"/api/v1/lectures/{lecture_id}/video-access?{parts.query}"


async def test_owner_gets_signed_url(client, user, auth_headers):
    lecture_id = await create_lecture(user.id)
    response = await client.get(f"/api/v1/lectures/{lecture_id}", headers=auth_headers)
    video_url = response.json()["video_url"]
    query = parse_qs(urlsplit(video_url).query)
    assert set(query) == {"expires", "signature"}
    assert int(query["expires"][0]) > time.time()

    assert (await client.get(access_path(video_url))).status_code == 200


async def test_signed_url_is_stable(user):
    lecture_id = await create_lecture(user.id)
    assert signed_video_url(lecture_id) == signed_video_url(lecture_id)


async def test_access_without_signature_forbidden(client, user):
    lecture_id = await create_lecture(user.id)
    response = await client.get(f"/api/v1/lectures/{lecture_id}/video-access")
    assert response.status_code == 403


async def test_access_with_wrong_signature_forbidden(client, user):
    lecture_id = await create_lecture(user.id)
    other_id = await create_lecture(user.id)
    video_url = signed_video_url(other_id)
    query = urlsplit(video_url).query
    response = await client.get(f"/api/v1/lectures/{lecture_id}/video-access?{query}")
    assert response.status_code == 403


async def test_expired_signature_forbidden(client, user):
    lecture_id = await create_lecture(user.id)
    expires = int(time.time()) - 1
    signature = video_signature(lecture_id, expires, None)
    response = await client.get(
        f"/api/v1/lectures/{lecture_id}/video-access",
        params={"expires": expires, "signature": signature},
    )
    assert response.status_code == 403


async def test_signed_url_expires(client, user, monkeypatch):
    lecture_id = await create_lecture(user.id)
    video_url = signed_video_url(lecture_id)
    later = time.time() + video_access.VIDEO_LINK_TTL_SEC * 2
    monkeypatch.setattr(video_access.time, "time", lambda: later)
    assert (await client.get(access_path(video_url))).status_code == 403


async def test_access_without_video_forbidden(client, user):
    lecture_id = await create_lecture(user.id, video_path=None)
    response = await client.get(access_path(signed_video_url(lecture_id)))
    assert response.status_code == 403


async def test_share_link_opens_video(client, user):
    lecture_id = await create_lecture(user.id)
    await create_share(user.id, lecture_id, "share-token")
    video_url = signed_video_url(lecture_id, "share-token")
    assert (await client.get(access_path(video_url))).status_code == 200


async def test_revoked_share_forbidden(client, user):
    lecture_id = await create_lecture(user.id)
    await create_share(user.id, lecture_id, "revoked-token")
    video_url = signed_video_url(lecture_id, "revoked-token")
    async with SessionLocal() as session:
        await session.execute(
            update(ShareLink)
            .where(ShareLink.token == "revoked-token")
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()
    assert (await client.get(access_path(video_url))).status_code == 403


async def test_share_of_other_lecture_forbidden(client, user):
    lecture_id = await create_lecture(user.id)
    other_id = await create_lecture(user.id)
    await create_share(user.id, other_id, "other-token")
    video_url = signed_video_url(lecture_id, "other-token")
    assert (await client.get(access_path(video_url))).status_code == 403


async def test_share_token_cannot_be_swapped(client, user):
    lecture_id = await create_lecture(user.id)
    await create_share(user.id, lecture_id, "real-token")
    owner_url = signed_video_url(lecture_id)
    response = await client.get(f"{access_path(owner_url)}&share=real-token")
    assert response.status_code == 403
