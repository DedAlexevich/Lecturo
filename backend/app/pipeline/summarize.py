import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chapter, Lecture, Summary, TranscriptSegment
from app.pipeline.runner import Report
from app.pipeline.stages import load_segments
from app.providers import LLM, get_llm

PROMPTS_DIR = Path(__file__).parent / "prompts"
PART_SECONDS = 15 * 60.0
TITLE_MAX_LENGTH = 300


@dataclass(frozen=True)
class Topic:
    title: str
    start: float


@dataclass(frozen=True)
class PartDigest:
    start: float
    end: float
    summary: str
    topics: list[Topic]


@dataclass(frozen=True)
class ChapterDraft:
    title: str
    start: float
    end: float
    summary: str


@cache
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def split_into_parts(
    segments: list[TranscriptSegment], seconds: float = PART_SECONDS
) -> list[list[TranscriptSegment]]:
    parts: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []
    for segment in segments:
        if current and segment.end - current[0].start > seconds:
            parts.append(current)
            current = []
        current.append(segment)
    if current:
        if parts and current[-1].end - current[0].start < seconds / 3:
            parts[-1].extend(current)
        else:
            parts.append(current)
    return parts


def format_part(part: list[TranscriptSegment]) -> str:
    return "\n".join(f"[{int(segment.start)}] {segment.text}" for segment in part)


def parse_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ValueError("LLM вернула ответ не в формате JSON") from error
    if not isinstance(data, dict):
        raise ValueError("LLM вернула JSON не того вида")
    return data


def parse_start(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_topics(items: Any) -> list[Topic]:
    topics = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        start = parse_start(item.get("start"))
        if title and start is not None:
            topics.append(Topic(title=title, start=start))
    return topics


async def digest_part(llm: LLM, part: list[TranscriptSegment]) -> PartDigest:
    data = parse_json(await llm.complete(load_prompt("map"), format_part(part), json_mode=True))
    return PartDigest(
        start=part[0].start,
        end=part[-1].end,
        summary=str(data.get("summary") or "").strip(),
        topics=parse_topics(data.get("topics")),
    )


def reduce_request(title: str, digests: list[PartDigest]) -> str:
    parts = [
        {
            "start": int(digest.start),
            "end": int(digest.end),
            "summary": digest.summary,
            "topics": [{"title": t.title, "start": int(t.start)} for t in digest.topics],
        }
        for digest in digests
    ]
    return json.dumps({"title": title, "parts": parts}, ensure_ascii=False)


def snap_to_segment(start: float, segment_starts: list[float]) -> float:
    return min(segment_starts, key=lambda value: abs(value - start))


def build_chapters(
    raw: Any, segments: list[TranscriptSegment], digests: list[PartDigest]
) -> list[ChapterDraft]:
    segment_starts = [segment.start for segment in segments]
    lecture_end = segments[-1].end
    drafts: dict[float, tuple[str, str]] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:TITLE_MAX_LENGTH]
        start = parse_start(item.get("start"))
        if not title or start is None:
            continue
        snapped = snap_to_segment(start, segment_starts)
        drafts.setdefault(snapped, (title, str(item.get("summary") or "").strip()))
    if not drafts:
        drafts = {
            digest.start: (fallback_title(digest, number), digest.summary)
            for number, digest in enumerate(digests, start=1)
        }
    ordered = sorted(drafts.items())
    starts = [segment_starts[0], *(start for start, _ in ordered[1:])]
    ends = [*starts[1:], lecture_end]
    return [
        ChapterDraft(title=title, start=start, end=end, summary=summary)
        for (_, (title, summary)), start, end in zip(ordered, starts, ends, strict=True)
    ]


def fallback_title(digest: PartDigest, number: int) -> str:
    return (digest.topics[0].title if digest.topics else f"Часть {number}")[:TITLE_MAX_LENGTH]


async def summarize(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    segments = await load_segments(session, lecture)
    await session.execute(delete(Chapter).where(Chapter.lecture_id == lecture.id))
    await session.execute(delete(Summary).where(Summary.lecture_id == lecture.id))
    if not segments:
        session.add(Summary(lecture_id=lecture.id, content_md=""))
        return

    llm = get_llm()
    parts = split_into_parts(segments)
    digests = []
    for done, part in enumerate(parts, start=1):
        digests.append(await digest_part(llm, part))
        await report(done / (len(parts) + 1))

    data = parse_json(
        await llm.complete(
            load_prompt("reduce"), reduce_request(lecture.title, digests), json_mode=True
        )
    )
    chapters = build_chapters(data.get("chapters"), segments, digests)
    content = str(data.get("summary_md") or "").strip() or "\n\n".join(
        f"## {chapter.title}\n\n{chapter.summary}" for chapter in chapters
    )

    session.add(Summary(lecture_id=lecture.id, content_md=content))
    session.add_all(
        Chapter(
            lecture_id=lecture.id,
            idx=idx,
            start=chapter.start,
            end=chapter.end,
            title=chapter.title,
            summary=chapter.summary,
        )
        for idx, chapter in enumerate(chapters)
    )
