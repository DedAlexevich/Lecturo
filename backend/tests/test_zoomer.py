import subprocess
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.api import admin_zoomer
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import AdminAuditEntry, User, ZoomerVideo
from app.pipeline.zoomer import process_zoomer_video
from app.services import zoomer

VIDEOS = "/api/v1/admin/zoomer/videos"
BROKEN_MP4 = b"\0\0\0\x18ftypisom" + b"\0" * 64


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}


def make_clip(
    path: Path, width: int, height: int, codec: str = "libx264", seconds: float = 1.5
) -> bytes:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:rate=15:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            codec,
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path / "storage")
    return tmp_path / "storage"


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    jobs: list[uuid.UUID] = []

    async def enqueue(video_id: uuid.UUID) -> None:
        jobs.append(video_id)

    monkeypatch.setattr(admin_zoomer, "enqueue_zoomer_video", enqueue)
    return jobs


@pytest.fixture
async def admin() -> AsyncIterator[User]:
    async with SessionLocal() as session:
        user = User(
            email=f"zoomer-{uuid.uuid4().hex[:10]}@example.org",
            display_name="Админ",
            is_admin=True,
        )
        session.add(user)
        await session.commit()
    yield user
    async with SessionLocal() as session:
        await session.execute(delete(ZoomerVideo))
        await session.execute(delete(AdminAuditEntry).where(AdminAuditEntry.actor_id == user.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


async def upload(client, admin: User, body: bytes, title: str = "Паркур", content_type="video/mp4"):
    return await client.post(
        VIDEOS,
        params={"title": title, "source": "Своя съёмка, CC BY 4.0"},
        content=body,
        headers={**headers(admin), "Content-Type": content_type},
    )


async def audit_actions(admin: User) -> list[str]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(AdminAuditEntry.action)
            .where(AdminAuditEntry.actor_id == admin.id)
            .order_by(AdminAuditEntry.created_at)
        )
        return list(rows)


async def test_vertical_clip_is_prepared_and_listed(client, admin, storage, queued, tmp_path):
    body = make_clip(tmp_path / "clip.mp4", 360, 640)

    response = await upload(client, admin, body)

    assert response.status_code == 201
    video = response.json()
    assert video["status"] == "processing"
    assert video["vertical"] is True
    assert video["video_url"] is None
    assert queued == [uuid.UUID(video["id"])]
    assert (await client.get("/api/v1/zoomer/videos")).json() == []

    assert await process_zoomer_video({}, video["id"]) == "ready"

    video_id = uuid.UUID(video["id"])
    assert zoomer.video_file(video_id).stat().st_size > 0
    assert zoomer.poster_file(video_id).read_bytes()[:2] == b"\xff\xd8"
    assert not zoomer.incoming_file(video_id).exists()
    [listed] = (await client.get(VIDEOS, headers=headers(admin))).json()
    assert listed["status"] == "ready"
    assert listed["size_bytes"] > 0
    assert (listed["width"], listed["height"]) == (360, 640)
    [clip] = (await client.get("/api/v1/zoomer/videos")).json()
    assert clip == {
        "id": video["id"],
        "title": "Паркур",
        "url": f"/zoomer/{video['id']}.mp4",
        "poster_url": f"/zoomer/{video['id']}.jpg",
        "duration_sec": pytest.approx(1.5, abs=0.2),
    }
    assert await audit_actions(admin) == ["zoomer_video_uploaded"]


async def test_disabled_and_unprocessed_clips_are_not_served(
    client, admin, storage, queued, tmp_path
):
    body = make_clip(tmp_path / "clip.mp4", 360, 640)
    video_id = (await upload(client, admin, body)).json()["id"]
    access = f"/api/v1/zoomer/videos/{video_id}/access"

    assert (await client.get(access)).status_code == 404

    await process_zoomer_video({}, video_id)
    assert (await client.get(access)).status_code == 200

    response = await client.patch(
        f"{VIDEOS}/{video_id}", json={"enabled": False}, headers=headers(admin)
    )
    assert response.json()["enabled"] is False
    assert response.json()["video_url"] is None
    assert (await client.get(access)).status_code == 404
    assert response.json()["poster_url"] is None
    assert (await client.get("/api/v1/zoomer/videos")).json() == []
    assert (await client.get(f"/api/v1/zoomer/videos/{uuid.uuid4()}/access")).status_code == 404


async def test_horizontal_webm_is_accepted_with_warning(client, admin, storage, queued, tmp_path):
    body = make_clip(tmp_path / "clip.webm", 320, 180, codec="libvpx-vp9")

    response = await upload(client, admin, body, content_type="video/webm")

    assert response.status_code == 201
    assert response.json()["vertical"] is False
    assert await process_zoomer_video({}, response.json()["id"]) == "ready"


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda tmp: b"just some text, not a video at all", zoomer.WRONG_TYPE),
        (lambda tmp: make_clip(tmp / "old.mp4", 360, 640, codec="mpeg4"), zoomer.WRONG_TYPE),
        (lambda tmp: BROKEN_MP4, zoomer.WRONG_TYPE),
    ],
)
async def test_wrong_type_is_rejected(client, admin, storage, queued, tmp_path, make, message):
    response = await upload(client, admin, make(tmp_path))

    assert response.status_code == 422
    assert response.json()["detail"] == message
    assert queued == []
    assert list((storage / "tmp").iterdir()) == []
    assert await audit_actions(admin) == ["zoomer_video_rejected"]


async def test_too_large_and_too_long_are_rejected(
    client, admin, storage, queued, tmp_path, monkeypatch
):
    body = make_clip(tmp_path / "clip.mp4", 360, 640, seconds=3)
    monkeypatch.setattr(get_settings(), "zoomer_max_duration_sec", 2)

    too_long = await upload(client, admin, body)
    monkeypatch.setattr(get_settings(), "zoomer_max_upload_mb", 0)
    too_large = await upload(client, admin, body)

    assert too_long.status_code == 422
    assert too_long.json()["detail"] == "Ролик длиннее 2 с"
    assert too_large.status_code == 413
    assert too_large.json()["detail"] == "Файл больше 0 МБ"
    assert queued == []


async def test_title_and_source_are_required(client, admin, storage, queued):
    response = await client.post(
        VIDEOS, params={"title": "Ролик"}, content=b"x", headers=headers(admin)
    )
    blank = await client.post(
        VIDEOS,
        params={"title": "Ролик", "source": "   "},
        content=b"x",
        headers=headers(admin),
    )

    assert response.status_code == 422
    assert blank.status_code == 422


async def test_failed_preparation_is_shown(client, admin, storage, queued, tmp_path):
    body = make_clip(tmp_path / "clip.mp4", 360, 640)
    video_id = (await upload(client, admin, body)).json()["id"]
    zoomer.incoming_file(uuid.UUID(video_id)).write_bytes(BROKEN_MP4)

    assert await process_zoomer_video({}, video_id) == "failed"

    [listed] = (await client.get(VIDEOS, headers=headers(admin))).json()
    assert listed["status"] == "failed"
    assert listed["error"]
    assert not zoomer.video_file(uuid.UUID(video_id)).exists()


async def test_order_update_and_delete(client, admin, storage, queued, tmp_path):
    body = make_clip(tmp_path / "clip.mp4", 360, 640)
    first = (await upload(client, admin, body, title="Первый")).json()["id"]
    second = (await upload(client, admin, body, title="Второй")).json()["id"]
    await process_zoomer_video({}, first)

    reordered = await client.put(
        "/api/v1/admin/zoomer/order", json={"ids": [second, first]}, headers=headers(admin)
    )
    partial = await client.put(
        "/api/v1/admin/zoomer/order", json={"ids": [second]}, headers=headers(admin)
    )
    renamed = await client.patch(
        f"{VIDEOS}/{first}", json={"title": "Новый"}, headers=headers(admin)
    )
    removed = await client.delete(f"{VIDEOS}/{first}", headers=headers(admin))
    missing = await client.delete(f"{VIDEOS}/{first}", headers=headers(admin))

    assert [item["id"] for item in reordered.json()] == [second, first]
    assert partial.status_code == 422
    assert renamed.json()["title"] == "Новый"
    assert removed.status_code == 204
    assert missing.status_code == 404
    assert not zoomer.video_file(uuid.UUID(first)).exists()
    assert [item["id"] for item in (await client.get(VIDEOS, headers=headers(admin))).json()] == [
        second
    ]
    assert await audit_actions(admin) == [
        "zoomer_video_uploaded",
        "zoomer_video_uploaded",
        "zoomer_videos_reordered",
        "zoomer_video_updated",
        "zoomer_video_deleted",
    ]


async def test_regular_user_has_no_access(client, auth_headers):
    for method, path in [
        ("GET", VIDEOS),
        ("POST", VIDEOS),
        ("PATCH", f"{VIDEOS}/{uuid.uuid4()}"),
        ("DELETE", f"{VIDEOS}/{uuid.uuid4()}"),
        ("PUT", "/api/v1/admin/zoomer/order"),
    ]:
        response = await client.request(method, path, headers=auth_headers, json={})
        assert response.status_code == 404, (method, path)
