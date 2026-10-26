import asyncio
import json
from pathlib import Path

MAX_DURATION_SEC = 4 * 3600
PROBE_TIMEOUT_SEC = 60.0


class MediaError(Exception):
    pass


async def probe_upload(path: Path) -> float:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type:format=duration",
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
        info = json.loads(stdout or b"{}")
        duration = float(info["format"]["duration"])
        streams = info.get("streams") or []
    except (ValueError, KeyError, TypeError) as error:
        raise MediaError("Файл не похож на видео или аудио") from error
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise MediaError("В файле нет звуковой дорожки")
    if duration <= 0:
        raise MediaError("Не удалось определить длительность записи")
    if duration > MAX_DURATION_SEC:
        raise MediaError("Запись длиннее 4 часов")
    return duration
