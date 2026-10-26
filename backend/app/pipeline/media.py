import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Lecture
from app.pipeline.runner import Report

logger = logging.getLogger(__name__)

MAX_DURATION_SEC = 4 * 3600
PROBE_TIMEOUT_SEC = 60.0
PROGRESS_INTERVAL_SEC = 2.0
VIDEO_HEIGHT = 720


class MediaError(Exception):
    pass


def original_path(lecture_id: uuid.UUID) -> Path:
    return get_settings().storage_dir / "originals" / str(lecture_id)


async def probe(path: Path, entries: str) -> dict[str, Any]:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        entries,
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), PROBE_TIMEOUT_SEC)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise MediaError("Не удалось прочитать файл") from None
    try:
        return json.loads(stdout or b"{}")
    except ValueError as error:
        raise MediaError("Файл не похож на видео или аудио") from error


async def probe_upload(path: Path) -> float:
    info = await probe(path, "stream=codec_type:format=duration")
    try:
        duration = float(info["format"]["duration"])
        streams = info.get("streams") or []
    except (KeyError, TypeError, ValueError) as error:
        raise MediaError("Файл не похож на видео или аудио") from error
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise MediaError("В файле нет звуковой дорожки")
    if duration <= 0:
        raise MediaError("Не удалось определить длительность записи")
    if duration > MAX_DURATION_SEC:
        raise MediaError("Запись длиннее 4 часов")
    return duration


async def probe_duration(path: Path) -> float:
    info = await probe(path, "format=duration")
    try:
        return float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError) as error:
        raise MediaError("Не удалось определить длительность записи") from error


async def has_video(path: Path) -> bool:
    info = await probe(path, "stream=codec_type:stream_disposition=attached_pic")
    return any(
        stream.get("codec_type") == "video"
        and not stream.get("disposition", {}).get("attached_pic")
        for stream in info.get("streams") or []
    )


async def run_ffmpeg(args: list[str], duration: float | None, report: Report, error: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-y",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr = asyncio.create_task(process.stderr.read())
    loop = asyncio.get_running_loop()
    reported_at = loop.time()
    try:
        async for line in process.stdout:
            key, _, value = line.decode().strip().partition("=")
            if key != "out_time_us" or not value.isdigit() or not duration:
                continue
            if loop.time() - reported_at >= PROGRESS_INTERVAL_SEC:
                reported_at = loop.time()
                await report(int(value) / 1_000_000 / duration)
        returncode = await process.wait()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    output = (await stderr).decode(errors="replace").strip()
    if returncode != 0:
        logger.warning("ffmpeg завершился с кодом %s: %s", returncode, output[-2000:])
        raise MediaError(error)


async def extract_audio(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    audio_dir = get_settings().storage_dir / "audio"
    await asyncio.to_thread(audio_dir.mkdir, parents=True, exist_ok=True)
    target = audio_dir / f"{lecture.id}.opus"
    partial = target.with_name(f"{target.name}.part")
    await run_ffmpeg(
        [
            "-i",
            str(original_path(lecture.id)),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            "-f",
            "opus",
            str(partial),
        ],
        lecture.duration_sec,
        report,
        "Не удалось извлечь звук из записи",
    )
    await asyncio.to_thread(partial.replace, target)
    lecture.audio_path = str(target)
    lecture.duration_sec = await probe_duration(target)


async def transcode_video(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    settings = get_settings()
    original = original_path(lecture.id)
    if await has_video(original):
        video_dir = settings.storage_dir / "videos"
        await asyncio.to_thread(video_dir.mkdir, parents=True, exist_ok=True)
        target = video_dir / f"{lecture.id}.mp4"
        partial = target.with_name(f"{target.name}.part")
        await run_ffmpeg(
            [
                "-i",
                str(original),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-vf",
                f"scale=-2:'2*trunc(min({VIDEO_HEIGHT},ih)/2)'",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "28",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(partial),
            ],
            lecture.duration_sec,
            report,
            "Не удалось пережать видео",
        )
        await asyncio.to_thread(partial.replace, target)
        lecture.video_path = str(target)
        lecture.video_expires_at = datetime.now(UTC) + timedelta(
            days=settings.free_video_retention_days
        )
    await asyncio.to_thread(original.unlink, missing_ok=True)
