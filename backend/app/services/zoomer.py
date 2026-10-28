import asyncio
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ZoomerVideo, ZoomerVideoStatus
from app.pipeline.media import MediaError, probe
from app.schemas.zoomer import ZoomerClipOut, ZoomerVideoOut

TOO_LARGE = "Файл больше {limit} МБ"
WRONG_TYPE = "Нужен ролик MP4 (H.264) или WebM"
TOO_LONG = "Ролик длиннее {limit} с"
NO_DURATION = "Не удалось определить длительность ролика"
NO_DISK = "Не удалось сохранить файл: нет места на сервере"
NOT_FOUND = "Ролик не найден"
ORDER_MISMATCH = "Порядок должен перечислять все ролики ровно по одному разу"

MP4_CODECS = {"h264"}
WEBM_CODECS = {"vp8", "vp9", "av1"}
VERTICAL_RATIO = 9 / 16
VERTICAL_TOLERANCE = 0.03
SNIFF_BYTES = 12


class ZoomerError(Exception):
    def __init__(self, message: str, code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class ClipInfo:
    container: str
    duration: float
    width: int
    height: int


def zoomer_dir() -> Path:
    return get_settings().storage_dir / "zoomer"


def video_file(video_id: uuid.UUID) -> Path:
    return zoomer_dir() / f"{video_id}.mp4"


def poster_file(video_id: uuid.UUID) -> Path:
    return zoomer_dir() / f"{video_id}.jpg"


def incoming_file(video_id: uuid.UUID) -> Path:
    return get_settings().storage_dir / "tmp" / f"zoomer-{video_id}.upload"


def upload_limit() -> int:
    return get_settings().zoomer_max_upload_mb * 1024 * 1024


def too_large() -> ZoomerError:
    return ZoomerError(TOO_LARGE.format(limit=get_settings().zoomer_max_upload_mb), 413)


def sniff(head: bytes) -> str | None:
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None


def is_vertical(width: int | None, height: int | None) -> bool | None:
    if not width or not height:
        return None
    return abs(width / height - VERTICAL_RATIO) <= VERTICAL_TOLERANCE


async def save_upload(stream: AsyncIterator[bytes], target: Path) -> str:
    limit = upload_limit()
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.{secrets.token_hex(4)}.part")
    written = 0
    head = b""
    try:
        descriptor = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            async for chunk in stream:
                if len(head) < SNIFF_BYTES:
                    head = (head + chunk)[:SNIFF_BYTES]
                written += len(chunk)
                if written > limit:
                    raise too_large()
                await asyncio.to_thread(handle.write, chunk)
        container = sniff(head)
        if container is None:
            raise ZoomerError(WRONG_TYPE)
        os.replace(part, target)
    except OSError as error:
        raise ZoomerError(NO_DISK, 507) from error
    finally:
        part.unlink(missing_ok=True)
    return container


def rotation_of(stream: dict) -> int:
    for item in stream.get("side_data_list") or []:
        if isinstance(item, dict) and "rotation" in item:
            try:
                return int(float(item["rotation"]))
            except (TypeError, ValueError):
                return 0
    return 0


async def inspect_clip(path: Path, container: str) -> ClipInfo:
    try:
        info = await probe(
            path,
            "stream=codec_type,codec_name,width,height:stream_side_data=rotation"
            ":format=duration,format_name",
        )
    except MediaError as error:
        raise ZoomerError(WRONG_TYPE) from error
    format_name = str((info.get("format") or {}).get("format_name") or "")
    video = next(
        (item for item in info.get("streams") or [] if item.get("codec_type") == "video"), None
    )
    codecs = MP4_CODECS if container == "mp4" else WEBM_CODECS
    expected = "mp4" if container == "mp4" else "webm"
    if video is None or video.get("codec_name") not in codecs or expected not in format_name:
        raise ZoomerError(WRONG_TYPE)
    try:
        duration = float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError) as error:
        raise ZoomerError(NO_DURATION) from error
    limit = get_settings().zoomer_max_duration_sec
    if duration <= 0:
        raise ZoomerError(NO_DURATION)
    if duration > limit:
        raise ZoomerError(TOO_LONG.format(limit=limit))
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if abs(rotation_of(video)) == 90:
        width, height = height, width
    return ClipInfo(container, duration, width, height)


async def next_position(session: AsyncSession) -> int:
    current = await session.scalar(select(func.max(ZoomerVideo.position)))
    return 0 if current is None else current + 1


async def list_videos(session: AsyncSession) -> list[ZoomerVideo]:
    rows = await session.scalars(
        select(ZoomerVideo).order_by(ZoomerVideo.position, ZoomerVideo.created_at)
    )
    return list(rows)


async def get_video(session: AsyncSession, video_id: uuid.UUID) -> ZoomerVideo:
    video = await session.get(ZoomerVideo, video_id, populate_existing=True)
    if video is None:
        raise ZoomerError(NOT_FOUND, 404)
    return video


def video_out(video: ZoomerVideo) -> ZoomerVideoOut:
    public = video.status == ZoomerVideoStatus.ready and video.enabled
    return ZoomerVideoOut(
        id=video.id,
        title=video.title,
        source=video.source,
        status=ZoomerVideoStatus(video.status),
        error=video.error,
        enabled=video.enabled,
        position=video.position,
        duration_sec=video.duration_sec,
        width=video.width,
        height=video.height,
        size_bytes=video.size_bytes,
        vertical=is_vertical(video.width, video.height),
        poster_url=f"/zoomer/{video.id}.jpg" if public else None,
        video_url=f"/zoomer/{video.id}.mp4" if public else None,
        created_at=video.created_at,
    )


async def public_clips(session: AsyncSession) -> list[ZoomerClipOut]:
    rows = await session.scalars(
        select(ZoomerVideo)
        .where(ZoomerVideo.enabled, ZoomerVideo.status == ZoomerVideoStatus.ready)
        .order_by(ZoomerVideo.position, ZoomerVideo.created_at)
    )
    return [
        ZoomerClipOut(
            id=video.id,
            title=video.title,
            url=f"/zoomer/{video.id}.mp4",
            poster_url=f"/zoomer/{video.id}.jpg",
            duration_sec=video.duration_sec,
        )
        for video in rows
    ]


async def is_public(session: AsyncSession, video_id: uuid.UUID) -> bool:
    query = select(ZoomerVideo.id).where(
        ZoomerVideo.id == video_id,
        ZoomerVideo.status == ZoomerVideoStatus.ready,
        ZoomerVideo.enabled,
    )
    return await session.scalar(query) is not None


def remove_files(video_id: uuid.UUID) -> None:
    for path in (video_file(video_id), poster_file(video_id), incoming_file(video_id)):
        path.unlink(missing_ok=True)


async def reorder(session: AsyncSession, ids: list[uuid.UUID]) -> list[ZoomerVideo]:
    videos = {video.id: video for video in await list_videos(session)}
    if len(ids) != len(set(ids)) or set(ids) != set(videos):
        raise ZoomerError(ORDER_MISMATCH)
    for position, video_id in enumerate(ids):
        videos[video_id].position = position
    return [videos[video_id] for video_id in ids]
