import asyncio
import logging
import uuid

from arq import create_pool

from app.core.db import SessionLocal
from app.models import ZoomerVideo, ZoomerVideoStatus
from app.pipeline.jobs import queue_settings
from app.pipeline.media import MediaError, encode, probe
from app.services import zoomer

logger = logging.getLogger(__name__)

ZOOMER_TIMEOUT_SEC = 900
CLIP_BOX = (720, 1280)
POSTER_WIDTH = 360
ENCODE_FAILED = "Не удалось перекодировать ролик"
POSTER_FAILED = "Не удалось сделать превью"


def zoomer_job_id(video_id: uuid.UUID) -> str:
    return f"zoomer:{video_id}"


async def ignore_progress(progress: float, stage: str | None = None) -> None:
    return None


def clip_args(source: str) -> list[str]:
    width, height = CLIP_BOX
    return [
        "-i",
        source,
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-vf",
        f"scale='min({width},iw)':'min({height},ih)'"
        ":force_original_aspect_ratio=decrease:force_divisible_by=2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-maxrate",
        "1500k",
        "-bufsize",
        "3000k",
        "-profile:v",
        "main",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
    ]


def poster_args(source: str, duration: float) -> list[str]:
    return [
        "-ss",
        f"{min(1.0, duration / 2):.2f}",
        "-i",
        source,
        "-frames:v",
        "1",
        "-vf",
        f"scale={POSTER_WIDTH}:-2",
        "-q:v",
        "4",
        "-f",
        "image2",
    ]


async def output_size(video_id: uuid.UUID) -> tuple[int, int]:
    info = await probe(zoomer.video_file(video_id), "stream=width,height")
    stream = (info.get("streams") or [{}])[0]
    return int(stream.get("width") or 0), int(stream.get("height") or 0)


async def prepare(video_id: uuid.UUID, duration: float) -> tuple[int, int, int]:
    source = zoomer.incoming_file(video_id)
    target = zoomer.video_file(video_id)
    await encode(clip_args(str(source)), target, duration, ignore_progress, ENCODE_FAILED)
    await encode(
        poster_args(str(target), duration),
        zoomer.poster_file(video_id),
        None,
        ignore_progress,
        POSTER_FAILED,
    )
    width, height = await output_size(video_id)
    size = (await asyncio.to_thread(target.stat)).st_size
    return width, height, size


async def process_zoomer_video(ctx: dict, video_id: str) -> str:
    video_uuid = uuid.UUID(video_id)
    async with SessionLocal() as session:
        video = await session.get(ZoomerVideo, video_uuid)
        if video is None or video.status != ZoomerVideoStatus.processing:
            await asyncio.to_thread(zoomer.incoming_file(video_uuid).unlink, missing_ok=True)
            return "skipped"
        duration = video.duration_sec or 0.0
    try:
        width, height, size = await prepare(video_uuid, duration)
        error = None
    except MediaError as failure:
        width = height = size = 0
        error = str(failure)
    except Exception:
        logger.exception("Не удалось подготовить ролик %s", video_id)
        width = height = size = 0
        error = ENCODE_FAILED
    finally:
        await asyncio.to_thread(zoomer.incoming_file(video_uuid).unlink, missing_ok=True)
    async with SessionLocal() as session:
        video = await session.get(ZoomerVideo, video_uuid, with_for_update=True)
        if video is None:
            await asyncio.to_thread(zoomer.remove_files, video_uuid)
            return "deleted"
        if error is None:
            video.status = ZoomerVideoStatus.ready
            video.width, video.height, video.size_bytes = width, height, size
        else:
            video.status = ZoomerVideoStatus.failed
            video.error = error
        await session.commit()
    if error is not None:
        await asyncio.to_thread(zoomer.remove_files, video_uuid)
    return "ready" if error is None else "failed"


async def enqueue_zoomer_video(video_id: uuid.UUID) -> None:
    redis = await create_pool(queue_settings())
    try:
        await redis.enqueue_job(
            "process_zoomer_video", str(video_id), _job_id=zoomer_job_id(video_id)
        )
    finally:
        await redis.aclose()
