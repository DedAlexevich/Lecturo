import asyncio
import re
from pathlib import Path

TARGET_CHUNK_SECONDS = 8 * 60
MIN_CHUNK_SECONDS = 5 * 60
MAX_CHUNK_SECONDS = 10 * 60
CHUNK_OVERLAP_SECONDS = 1.5
CHUNK_CONCURRENCY = 3
SILENCE_NOISE_DB = -35
SILENCE_MIN_SECONDS = 1.0
SILENCE_START = re.compile(r"silence_start: ([0-9.]+)")
SILENCE_END = re.compile(r"silence_end: ([0-9.]+)")


class AudioChunkError(RuntimeError):
    pass


def chunk_boundaries(
    duration: float, silences: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    ranges = []
    start = 0.0
    silence_centers = [(begin + end) / 2 for begin, end in silences if end > begin]
    while duration - start > MAX_CHUNK_SECONDS:
        earliest = start + MIN_CHUNK_SECONDS
        latest = min(start + MAX_CHUNK_SECONDS, duration - MIN_CHUNK_SECONDS)
        target = min(start + TARGET_CHUNK_SECONDS, latest)
        candidates = [center for center in silence_centers if earliest <= center <= latest]
        end = min(candidates, key=lambda center: abs(center - target)) if candidates else target
        ranges.append((start, end))
        start = end
    ranges.append((start, duration))
    return ranges


def chunk_windows(
    duration: float, silences: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    return [
        (
            max(0.0, start - CHUNK_OVERLAP_SECONDS),
            min(duration, end + CHUNK_OVERLAP_SECONDS),
        )
        for start, end in chunk_boundaries(duration, silences)
    ]


def parse_silences(output: str) -> list[tuple[float, float]]:
    silences = []
    start = None
    for line in output.splitlines():
        if match := SILENCE_START.search(line):
            start = float(match.group(1))
        elif match := SILENCE_END.search(line):
            end = float(match.group(1))
            if start is not None and end > start:
                silences.append((start, end))
            start = None
    return silences


async def detect_silences(audio_path: Path) -> list[tuple[float, float]]:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-i",
        str(audio_path),
        "-af",
        f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_SECONDS}",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await process.communicate()
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise AudioChunkError("Не удалось найти паузы в аудиозаписи")
    return parse_silences(stderr.decode(errors="replace"))


async def split_audio(
    audio_path: Path,
    duration: float,
    target_dir: Path,
) -> list[tuple[Path, float]]:
    await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
    silences = await detect_silences(audio_path)
    windows = chunk_windows(duration, silences)
    if len(windows) < 2:
        return []

    semaphore = asyncio.Semaphore(CHUNK_CONCURRENCY)

    async def split(index: int, start: float, end: float) -> tuple[Path, float]:
        target = target_dir / f"chunk-{index:03d}.opus"
        async with semaphore:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{start:.3f}",
                "-i",
                str(audio_path),
                "-t",
                f"{end - start:.3f}",
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
                str(target),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await process.communicate()
            except asyncio.CancelledError:
                process.kill()
                await process.wait()
                raise
            if process.returncode:
                raise AudioChunkError("Не удалось нарезать аудиозапись")
            return target, start

    results = await asyncio.gather(
        *(split(index, start, end) for index, (start, end) in enumerate(windows)),
        return_exceptions=True,
    )
    error = next((result for result in results if isinstance(result, BaseException)), None)
    if error is not None:
        raise AudioChunkError("Не удалось нарезать аудиозапись") from error
    return results
