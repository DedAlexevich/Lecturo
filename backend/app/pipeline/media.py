import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Lecture, User
from app.pipeline.runner import Report
from app.services import quota

logger = logging.getLogger(__name__)

MAX_DURATION_SEC = 4 * 3600
PROBE_TIMEOUT_SEC = 60.0
PROGRESS_INTERVAL_SEC = 2.0
VIDEO_HEIGHT = 720
VIDEO_PRESET = "veryfast"
PLAYER_PROFILES = {"Constrained Baseline", "Baseline", "Main", "High"}


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


async def media_streams(path: Path) -> list[dict[str, Any]]:
    info = await probe(
        path, "stream=codec_type,codec_name,profile,height,pix_fmt:stream_disposition=attached_pic"
    )
    return info.get("streams") or []


def is_picture(stream: dict[str, Any]) -> bool:
    return bool(stream.get("disposition", {}).get("attached_pic"))


def first_stream(streams: list[dict[str, Any]], codec_type: str) -> dict[str, Any] | None:
    return next((stream for stream in streams if stream.get("codec_type") == codec_type), None)


def has_video(streams: list[dict[str, Any]]) -> bool:
    return any(stream.get("codec_type") == "video" and not is_picture(stream) for stream in streams)


def fits_player(streams: list[dict[str, Any]]) -> bool:
    video = first_stream(streams, "video")
    audio = first_stream(streams, "audio")
    return (
        video is not None
        and audio is not None
        and not is_picture(video)
        and video.get("codec_name") == "h264"
        and video.get("profile") in PLAYER_PROFILES
        and video.get("pix_fmt") == "yuv420p"
        and 0 < int(video.get("height") or 0) <= VIDEO_HEIGHT
        and audio.get("codec_name") == "aac"
    )


def video_args(original: Path, streams: list[dict[str, Any]]) -> list[str]:
    args = ["-i", str(original), "-map", "0:v:0", "-map", "0:a:0"]
    if fits_player(streams):
        args += ["-c", "copy"]
    else:
        args += [
            "-vf",
            f"scale=-2:'2*trunc(min({VIDEO_HEIGHT},ih)/2)'",
            "-c:v",
            "libx264",
            "-preset",
            VIDEO_PRESET,
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
        ]
    return [*args, "-movflags", "+faststart", "-f", "mp4"]


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
        output = (await stderr).decode(errors="replace").strip()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        stderr.cancel()
    if returncode != 0:
        logger.warning("ffmpeg завершился с кодом %s: %s", returncode, output[-2000:])
        raise MediaError(error)


async def encode(
    args: list[str], target: Path, duration: float | None, report: Report, error: str
) -> None:
    tmp_dir = get_settings().storage_dir / "tmp"
    await asyncio.to_thread(tmp_dir.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
    partial = tmp_dir / target.name
    try:
        await run_ffmpeg([*args, str(partial)], duration, report, error)
        await asyncio.to_thread(partial.replace, target)
    finally:
        await asyncio.to_thread(partial.unlink, missing_ok=True)


async def extract_audio(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    target = get_settings().storage_dir / "audio" / f"{lecture.id}.opus"
    await encode(
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
        ],
        target,
        lecture.duration_sec,
        report,
        "Не удалось извлечь звук из записи",
    )
    lecture.audio_path = str(target)
    lecture.duration_sec = await probe_duration(target)


async def transcode_video(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    settings = get_settings()
    original = original_path(lecture.id)
    try:
        streams = await media_streams(original)
        if has_video(streams):
            target = settings.storage_dir / "videos" / f"{lecture.id}.mp4"
            await encode(
                video_args(original, streams),
                target,
                lecture.duration_sec,
                report,
                "Не удалось пережать видео",
            )
            lecture.video_path = str(target)
            owner = await session.get(User, lecture.owner_id, with_for_update=True)
            now = datetime.now(UTC)
            days = await quota.video_retention_days(session, owner, now=now, settings=settings)
            lecture.video_expires_at = now + timedelta(days=days)
    except MediaError:
        await asyncio.to_thread(original.unlink, missing_ok=True)
        raise
    await asyncio.to_thread(original.unlink, missing_ok=True)
