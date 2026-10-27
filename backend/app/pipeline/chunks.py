import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.providers.base import Segment

logger = logging.getLogger(__name__)

SILENCE_NOISE_DB = -35
SILENCE_MIN_SECONDS = 0.4
SEARCH_WINDOW_SECONDS = 30.0
OVERLAP_SECONDS = 2.5
FFMPEG_TIMEOUT_SECONDS = 600.0
DUPLICATE_START_GAP = 1.5
MIN_SEGMENT_SECONDS = 0.05

SILENCE_START = re.compile(r"silence_start: (-?[\d.]+)")
SILENCE_END = re.compile(r"silence_end: (-?[\d.]+)")


class ChunkingError(Exception):
    pass


@dataclass(frozen=True)
class Part:
    index: int
    start: float
    end: float
    cut_start: float
    cut_end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def parse_silences(log: str, duration: float) -> list[tuple[float, float]]:
    silences = []
    start: float | None = None
    for line in log.splitlines():
        if (found := SILENCE_START.search(line)) is not None:
            start = max(float(found.group(1)), 0.0)
        elif (found := SILENCE_END.search(line)) is not None and start is not None:
            silences.append((start, min(float(found.group(1)), duration)))
            start = None
    if start is not None and start < duration:
        silences.append((start, duration))
    return silences


def choose_cut(ideal: float, silences: list[tuple[float, float]], window: float) -> float:
    candidates = [(start + end) / 2 for start, end in silences]
    near = [point for point in candidates if abs(point - ideal) <= window]
    return min(near, key=lambda point: abs(point - ideal)) if near else ideal


def plan_parts(
    duration: float,
    silences: list[tuple[float, float]],
    *,
    target: float,
    window: float = SEARCH_WINDOW_SECONDS,
    overlap: float = OVERLAP_SECONDS,
) -> list[Part]:
    count = max(2, round(duration / max(target, 1.0)))
    cuts: list[float] = []
    for number in range(1, count):
        cut = choose_cut(duration * number / count, silences, window)
        previous = cuts[-1] if cuts else 0.0
        if cut - previous > 2 * overlap and duration - cut > 2 * overlap:
            cuts.append(cut)
    bounds = [0.0, *cuts, duration]
    half = overlap / 2
    last = len(bounds) - 2
    return [
        Part(
            index=index,
            start=0.0 if index == 0 else bounds[index] - half,
            end=duration if index == last else bounds[index + 1] + half,
            cut_start=bounds[index],
            cut_end=bounds[index + 1],
        )
        for index in range(last + 1)
    ]


async def run_ffmpeg(args: list[str]) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-nostats",
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        raise ChunkingError("ffmpeg недоступен") from error
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), FFMPEG_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ChunkingError("ffmpeg не уложился во время") from None
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    output = stderr.decode(errors="replace")
    if process.returncode != 0:
        raise ChunkingError(f"ffmpeg завершился с кодом {process.returncode}: {output[-500:]}")
    return output


async def detect_silences(audio: Path, duration: float) -> list[tuple[float, float]]:
    log = await run_ffmpeg(
        [
            "-i",
            str(audio),
            "-map",
            "0:a:0",
            "-af",
            f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_SECONDS}",
            "-f",
            "null",
            "-",
        ]
    )
    return parse_silences(log, duration)


async def cut_part(audio: Path, part: Part, target: Path) -> None:
    await run_ffmpeg(
        [
            "-y",
            "-v",
            "error",
            "-ss",
            f"{part.start:.3f}",
            "-t",
            f"{part.duration:.3f}",
            "-i",
            str(audio),
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
        ]
    )


async def split_audio(
    audio: Path, duration: float, workdir: Path, *, target: float
) -> list[tuple[Part, Path]]:
    silences = await detect_silences(audio, duration)
    parts = plan_parts(duration, silences, target=target)
    files = [workdir / f"part-{part.index:03d}.opus" for part in parts]
    await asyncio.gather(
        *(cut_part(audio, part, file) for part, file in zip(parts, files, strict=True))
    )
    return list(zip(parts, files, strict=True))


def normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def merge_segments(
    results: list[tuple[Part, list[Segment]]], duration: float | None = None
) -> list[Segment]:
    last = len(results) - 1
    collected: list[Segment] = []
    for position, (part, segments) in enumerate(results):
        for segment in segments:
            start = segment.start + part.start
            end = segment.end + part.start
            middle = (start + end) / 2
            if position > 0 and middle < part.cut_start:
                continue
            if position < last and middle >= part.cut_end:
                continue
            collected.append(Segment(start=start, end=end, text=segment.text))
    collected.sort(key=lambda segment: (segment.start, segment.end))

    merged: list[Segment] = []
    for segment in collected:
        start, end = segment.start, segment.end
        if duration is not None:
            end = min(end, duration)
        if merged:
            previous = merged[-1]
            same_text = normalize(segment.text) == normalize(previous.text)
            if same_text and abs(start - previous.start) <= DUPLICATE_START_GAP:
                continue
            start = max(start, previous.end)
        if end - start < MIN_SEGMENT_SECONDS:
            continue
        merged.append(Segment(start=round(start, 3), end=round(end, 3), text=segment.text))
    return merged
