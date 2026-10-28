import time
import uuid
from urllib.parse import urlsplit

import pytest

from app.api import lectures as lectures_api
from app.core.db import SessionLocal
from app.models import Lecture, LectureStatus, ShareLink, SourceType
from app.pipeline.download import LinkError
from app.pipeline.video_access import media_signature, signed_stream_url

DISK_URL = "https://disk.yandex.ru/i/AbCdEf"
MEDIA_URL = "https://downloader.disk.yandex.ru/disk/lecture.mp4"


async def create_link_lecture(owner_id: uuid.UUID, source_url: str = DISK_URL) -> uuid.UUID:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=owner_id,
            title="Пределы",
            status=LectureStatus.ready,
            source_type=SourceType.link,
            source_url=source_url,
        )
        session.add(lecture)
        await session.commit()
        return lecture.id


@pytest.fixture
def disk(monkeypatch):
    calls: list[str] = []

    async def resolve(url: str) -> tuple[str, str]:
        calls.append(url)
        return "lecture.mp4", MEDIA_URL

    monkeypatch.setattr(lectures_api, "resolve_yandex_disk", resolve)
    return calls


def stream_path(video_url: str) -> str:
    parts = urlsplit(video_url)
    return f"{parts.path}?{parts.query}"


async def test_disk_lecture_gets_stream_url(client, user, auth_headers, disk):
    lecture_id = await create_link_lecture(user.id)
    response = await client.get(f"/api/v1/lectures/{lecture_id}", headers=auth_headers)
    video_url = response.json()["video_url"]
    assert video_url.startswith(f"/api/v1/lectures/{lecture_id}/stream?")

    redirect = await client.get(stream_path(video_url))
    assert redirect.status_code == 302
    assert redirect.headers["location"] == MEDIA_URL
    assert disk == [DISK_URL]


async def test_other_links_have_no_video_url(client, user, auth_headers):
    lecture_id = await create_link_lecture(user.id, "https://www.youtube.com/watch?v=abc")
    response = await client.get(f"/api/v1/lectures/{lecture_id}", headers=auth_headers)
    assert response.json()["video_url"] is None


async def test_stream_without_signature_forbidden(client, user, disk):
    lecture_id = await create_link_lecture(user.id)
    response = await client.get(f"/api/v1/lectures/{lecture_id}/stream")
    assert response.status_code == 403
    assert disk == []


async def test_video_signature_does_not_open_stream(client, user, disk):
    lecture_id = await create_link_lecture(user.id)
    expires = int(time.time()) + 60
    signature = media_signature("video", lecture_id, expires, None)
    response = await client.get(
        f"/api/v1/lectures/{lecture_id}/stream",
        params={"expires": expires, "signature": signature},
    )
    assert response.status_code == 403


async def test_stream_of_non_disk_lecture_not_found(client, user, disk):
    lecture_id = await create_link_lecture(user.id, "https://rutube.ru/video/abc/")
    response = await client.get(stream_path(signed_stream_url(lecture_id)))
    assert response.status_code == 404
    assert disk == []


async def test_stream_reports_disk_error(client, user, monkeypatch):
    async def resolve(url: str) -> tuple[str, str]:
        raise LinkError("Файл на Яндекс Диске не найден или закрыт")

    monkeypatch.setattr(lectures_api, "resolve_yandex_disk", resolve)
    lecture_id = await create_link_lecture(user.id)
    response = await client.get(stream_path(signed_stream_url(lecture_id)))
    assert response.status_code == 502


async def test_share_opens_stream(client, user, disk):
    lecture_id = await create_link_lecture(user.id)
    other_id = await create_link_lecture(user.id)
    async with SessionLocal() as session:
        session.add(ShareLink(token="disk-token", owner_id=user.id, lecture_id=lecture_id))
        await session.commit()

    public = await client.get("/api/v1/public/disk-token")
    assert public.status_code == 200
    video_url = public.json()["lecture"]["video_url"]
    assert (await client.get(stream_path(video_url))).status_code == 302
    assert (
        await client.get(stream_path(signed_stream_url(other_id, "disk-token")))
    ).status_code == 403
