import re
import textwrap
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

LINE_WIDTH = 42
MAX_LINES = 2
UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


class Segment(Protocol):
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    lines: list[str]


def format_timestamp(seconds: float, separator: str) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{ms:03d}"


def split_segment(segment: Segment) -> list[Cue]:
    text = " ".join(segment.text.split())
    if not text:
        return []
    lines = textwrap.wrap(text, LINE_WIDTH, break_long_words=True, break_on_hyphens=False)
    groups = [lines[i : i + MAX_LINES] for i in range(0, len(lines), MAX_LINES)]
    end = max(segment.end, segment.start)
    total_chars = sum(len(line) for line in lines)
    cues = []
    start = segment.start
    passed_chars = 0
    for group in groups:
        passed_chars += sum(len(line) for line in group)
        group_end = segment.start + (end - segment.start) * passed_chars / total_chars
        cues.append(Cue(start=start, end=group_end, lines=group))
        start = group_end
    return cues


def build_cues(segments: Iterable[Segment]) -> list[Cue]:
    return [cue for segment in segments for cue in split_segment(segment)]


def to_srt(segments: Iterable[Segment]) -> str:
    blocks = [
        f"{number}\n"
        f"{format_timestamp(cue.start, ',')} --> {format_timestamp(cue.end, ',')}\n"
        + "\n".join(cue.lines)
        for number, cue in enumerate(build_cues(segments), start=1)
    ]
    return "".join(f"{block}\n\n" for block in blocks)


def to_vtt(segments: Iterable[Segment]) -> str:
    blocks = [
        f"{format_timestamp(cue.start, '.')} --> {format_timestamp(cue.end, '.')}\n"
        + "\n".join(cue.lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for cue in build_cues(segments)
    ]
    return "WEBVTT\n\n" + "".join(f"{block}\n\n" for block in blocks)


def safe_filename(title: str) -> str:
    cleaned = " ".join(UNSAFE_FILENAME_CHARS.sub(" ", title).split()).strip(" .")
    return cleaned[:150] or "lecture"


def content_disposition(title: str, extension: str) -> str:
    name = safe_filename(title)
    ascii_name = " ".join(name.encode("ascii", "ignore").decode().split()).strip(" .") or "lecture"
    return (
        f'attachment; filename="{ascii_name}.{extension}"; '
        f"filename*=UTF-8''{quote(f'{name}.{extension}', safe='')}"
    )
