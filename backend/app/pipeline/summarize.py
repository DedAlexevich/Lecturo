import hashlib
import json
import logging
import math
import re
import uuid
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Chapter, Lecture, Summary, TranscriptSegment
from app.pipeline.runner import Report
from app.pipeline.stages import load_segments, require_ai_transfer
from app.providers import LLM, get_llm

PROMPTS_DIR = Path(__file__).parent / "prompts"
PART_SECONDS = 15 * 60.0
SHORT_LECTURE_SECONDS = 20 * 60.0
SHORT_PART_SECONDS = 3 * 60.0
SHORT_CHAPTER_MAX_SECONDS = 5 * 60.0
CHAPTERS_REQUIRED_FROM_SECONDS = 3 * 60.0
TITLE_MAX_LENGTH = 300
MAP_ATTEMPTS = 2
REDUCE_ATTEMPTS = 2
RAW_PART_CHAR_LIMIT = 6000
DIGEST_CACHE_TTL_SECONDS = 3 * 24 * 3600
LATEX_BACKSLASH = re.compile(r"\\\\|\\(?=([A-Za-z]{2,}))")
JSON_ESCAPE_LETTERS = "bfnrtu"
LATEX_COMMANDS_LIKE_ESCAPES = frozenset(
    {
        "backslash",
        "bar",
        "bcancel",
        "because",
        "begin",
        "beta",
        "big",
        "bigcap",
        "bigcup",
        "bigg",
        "biggl",
        "biggr",
        "bigl",
        "bigoplus",
        "bigotimes",
        "bigr",
        "bigwedge",
        "bigvee",
        "binom",
        "bm",
        "bmatrix",
        "bmod",
        "boldsymbol",
        "bot",
        "bowtie",
        "boxed",
        "bullet",
        "fbox",
        "flat",
        "forall",
        "frac",
        "frak",
        "frown",
        "nabla",
        "natural",
        "ne",
        "nearrow",
        "neg",
        "neq",
        "newline",
        "nexists",
        "ngeq",
        "ni",
        "nleq",
        "nmid",
        "not",
        "notin",
        "nparallel",
        "nsubseteq",
        "nu",
        "nwarrow",
        "rangle",
        "rbrace",
        "rbrack",
        "rceil",
        "rfloor",
        "rho",
        "right",
        "rightarrow",
        "rightharpoonup",
        "rightleftharpoons",
        "rm",
        "rvert",
        "rVert",
        "tan",
        "tanh",
        "tau",
        "tbinom",
        "text",
        "textbf",
        "textit",
        "textrm",
        "texttt",
        "tfrac",
        "therefore",
        "theta",
        "thinspace",
        "tilde",
        "times",
        "to",
        "top",
        "triangle",
        "triangleleft",
        "triangleq",
        "triangleright",
        "underbrace",
        "underline",
        "underset",
        "uparrow",
        "updownarrow",
        "upharpoonright",
        "uplus",
        "upsilon",
    }
)

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class ChapterPlan:
    min_count: int
    max_count: int
    max_seconds: float | None
    length_hint: str


@cache
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def render_prompt(name: str, **params: Any) -> str:
    text = load_prompt(name)
    for key, value in params.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def format_duration(seconds: float) -> str:
    total = max(int(round(seconds)), 0)
    minutes, rest = divmod(total, 60)
    if minutes and rest:
        return f"{minutes} мин {rest} с"
    if minutes:
        return f"{minutes} мин"
    return f"{rest} с"


def part_seconds_for(duration: float) -> float:
    return SHORT_PART_SECONDS if duration <= SHORT_LECTURE_SECONDS else PART_SECONDS


def topic_range(part_duration: float, short: bool) -> tuple[int, int]:
    fastest, slowest = (60.0, 150.0) if short else (180.0, 450.0)
    return max(1, math.ceil(part_duration / slowest)), max(1, math.ceil(part_duration / fastest))


def plan_chapters(duration: float) -> ChapterPlan:
    if duration <= SHORT_LECTURE_SECONDS:
        if duration <= CHAPTERS_REQUIRED_FROM_SECONDS:
            return ChapterPlan(1, max(1, math.ceil(duration / 60)), None, "не длиннее 5 минут")
        min_count = max(3, math.ceil(duration / SHORT_CHAPTER_MAX_SECONDS))
        max_count = max(min_count + 1, math.ceil(duration / 120))
        return ChapterPlan(
            min_count,
            max_count,
            SHORT_CHAPTER_MAX_SECONDS,
            "в среднем 2–3 минуты, не длиннее 5 минут",
        )
    min_count = max(4, math.ceil(duration / 900))
    max_count = max(min_count + 1, math.ceil(duration / 300))
    return ChapterPlan(min_count, max_count, None, "обычно 5–15 минут")


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


def double_latex_backslash(match: re.Match[str]) -> str:
    word = match.group(1)
    if word is None:
        return match.group()
    if word[0] in JSON_ESCAPE_LETTERS and word not in LATEX_COMMANDS_LIKE_ESCAPES:
        return match.group()
    return "\\\\"


def escape_latex(text: str) -> str:
    return LATEX_BACKSLASH.sub(double_latex_backslash, text)


def parse_json(content: str) -> dict[str, Any]:
    text = escape_latex(content[content.find("{") : content.rfind("}") + 1])
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


def map_prompt(part: list[TranscriptSegment], short: bool) -> str:
    duration = part[-1].end - part[0].start
    min_topics, max_topics = topic_range(duration, short)
    return render_prompt(
        "map",
        duration=format_duration(duration),
        min_topics=min_topics,
        max_topics=max_topics,
    )


def raw_part_summary(part: list[TranscriptSegment]) -> str:
    text = " ".join(segment.text.strip() for segment in part)
    if len(text) <= RAW_PART_CHAR_LIMIT:
        return text
    return text[:RAW_PART_CHAR_LIMIT].rsplit(" ", 1)[0] + " …"


async def request_digest(
    llm: LLM, part: list[TranscriptSegment], short: bool = False
) -> PartDigest | None:
    system = map_prompt(part, short)
    for _ in range(MAP_ATTEMPTS):
        try:
            data = parse_json(await llm.complete(system, format_part(part), json_mode=True))
        except ValueError:
            continue
        summary = str(data.get("summary") or "").strip()
        if summary:
            return PartDigest(
                start=part[0].start,
                end=part[-1].end,
                summary=summary,
                topics=parse_topics(data.get("topics")),
            )
    return None


def raw_digest(part: list[TranscriptSegment]) -> PartDigest:
    logger.warning(
        "Содержание части %s–%s (с) не получено после %s попыток, взят текст расшифровки",
        int(part[0].start),
        int(part[-1].end),
        MAP_ATTEMPTS,
    )
    return PartDigest(
        start=part[0].start, end=part[-1].end, summary=raw_part_summary(part), topics=[]
    )


def digest_field(system: str, part: list[TranscriptSegment]) -> str:
    return hashlib.sha256(f"{system}\n{format_part(part)}".encode()).hexdigest()


def load_digest(raw: bytes | None) -> PartDigest | None:
    if raw is None:
        return None
    data = json.loads(raw)
    return PartDigest(
        start=data["start"],
        end=data["end"],
        summary=data["summary"],
        topics=[Topic(**topic) for topic in data["topics"]],
    )


class DigestCache:
    def __init__(self, lecture_id: uuid.UUID) -> None:
        self.key = f"summarize:digests:{lecture_id}"
        self.redis = Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2
        )

    async def get(self, field: str) -> PartDigest | None:
        try:
            return load_digest(await self.redis.hget(self.key, field))
        except (OSError, RedisError, ValueError, KeyError, TypeError):
            logger.warning("Не удалось прочитать содержание части из кеша", exc_info=True)
            return None

    async def put(self, field: str, digest: PartDigest) -> None:
        try:
            await self.redis.hset(self.key, field, json.dumps(asdict(digest), ensure_ascii=False))
            await self.redis.expire(self.key, DIGEST_CACHE_TTL_SECONDS)
        except (OSError, RedisError):
            logger.warning("Не удалось сохранить содержание части в кеш", exc_info=True)

    async def clear(self) -> None:
        try:
            await self.redis.delete(self.key)
        except (OSError, RedisError):
            logger.warning("Не удалось очистить кеш содержания частей", exc_info=True)

    async def close(self) -> None:
        await self.redis.aclose()


async def digest_parts(
    llm: LLM,
    parts: list[list[TranscriptSegment]],
    short: bool,
    cache: DigestCache,
    report: Report,
) -> list[PartDigest]:
    digests = []
    for done, part in enumerate(parts, start=1):
        field = digest_field(map_prompt(part, short), part)
        digest = await cache.get(field)
        if digest is None:
            digest = await request_digest(llm, part, short)
            if digest is None:
                digest = raw_digest(part)
            else:
                await cache.put(field, digest)
        digests.append(digest)
        await report(done / (len(parts) + 1))
    return digests


def reduce_prompt(duration: float, plan: ChapterPlan) -> str:
    return render_prompt(
        "reduce",
        duration=format_duration(duration),
        min_chapters=plan.min_count,
        max_chapters=plan.max_count,
        length_hint=plan.length_hint,
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


async def reduce_parts(
    llm: LLM, title: str, duration: float, plan: ChapterPlan, digests: list[PartDigest]
) -> dict[str, Any]:
    system = reduce_prompt(duration, plan)
    request = reduce_request(title, digests)
    for _ in range(REDUCE_ATTEMPTS - 1):
        try:
            return parse_json(await llm.complete(system, request, json_mode=True))
        except ValueError:
            logger.warning("Ответ LLM с главами не разобран, запрос повторяется")
    return parse_json(await llm.complete(system, request, json_mode=True))


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


def split_point(chapter: ChapterDraft, segment_starts: list[float]) -> float | None:
    inside = [start for start in segment_starts if chapter.start < start < chapter.end]
    if not inside:
        return None
    middle = (chapter.start + chapter.end) / 2
    return min(inside, key=lambda start: abs(start - middle))


def continuation_title(
    chapter: ChapterDraft, point: float, digests: list[PartDigest], used: set[str]
) -> str:
    topics = [
        topic
        for digest in digests
        for topic in digest.topics
        if chapter.start < topic.start < chapter.end and topic.title[:TITLE_MAX_LENGTH] not in used
    ]
    if topics:
        return min(topics, key=lambda topic: abs(topic.start - point)).title[:TITLE_MAX_LENGTH]
    base = chapter.title[: TITLE_MAX_LENGTH - 20]
    title = f"{base} (продолжение)"
    number = 2
    while title in used:
        title = f"{base} (продолжение {number})"
        number += 1
    return title


def summary_at(point: float, digests: list[PartDigest]) -> str:
    for digest in digests:
        if digest.start <= point <= digest.end:
            return digest.summary
    return ""


def split_oversized(
    chapters: list[ChapterDraft],
    segments: list[TranscriptSegment],
    digests: list[PartDigest],
    plan: ChapterPlan,
) -> list[ChapterDraft]:
    segment_starts = [segment.start for segment in segments]
    result = list(chapters)
    unsplittable: set[int] = set()
    while True:
        candidates = [
            (chapter.end - chapter.start, index)
            for index, chapter in enumerate(result)
            if index not in unsplittable
        ]
        if not candidates:
            return result
        length, index = max(candidates)
        too_long = plan.max_seconds is not None and length > plan.max_seconds
        if not too_long and len(result) >= plan.min_count:
            return result
        chapter = result[index]
        point = split_point(chapter, segment_starts)
        if point is None:
            unsplittable.add(index)
            continue
        title = continuation_title(chapter, point, digests, {c.title for c in result})
        result[index : index + 1] = [
            ChapterDraft(chapter.title, chapter.start, point, chapter.summary),
            ChapterDraft(title, point, chapter.end, summary_at(point, digests)),
        ]
        unsplittable = {i if i < index else i + 1 for i in unsplittable}


def fallback_title(digest: PartDigest, number: int) -> str:
    return (digest.topics[0].title if digest.topics else f"Часть {number}")[:TITLE_MAX_LENGTH]


async def clear_previous(session: AsyncSession, lecture: Lecture) -> None:
    await session.execute(delete(Chapter).where(Chapter.lecture_id == lecture.id))
    await session.execute(delete(Summary).where(Summary.lecture_id == lecture.id))


async def summarize(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    await require_ai_transfer(session, lecture)
    segments = await load_segments(session, lecture)
    if not segments:
        await clear_previous(session, lecture)
        session.add(Summary(lecture_id=lecture.id, content_md=""))
        return

    llm = get_llm()
    duration = segments[-1].end
    plan = plan_chapters(duration)
    short = duration <= SHORT_LECTURE_SECONDS
    parts = split_into_parts(segments, part_seconds_for(duration))
    cache = DigestCache(lecture.id)
    try:
        digests = await digest_parts(llm, parts, short, cache, report)
        data = await reduce_parts(llm, lecture.title, duration, plan, digests)
        chapters = split_oversized(
            build_chapters(data.get("chapters"), segments, digests), segments, digests, plan
        )
        content = str(data.get("summary_md") or "").strip() or "\n\n".join(
            f"## {chapter.title}\n\n{chapter.summary}" for chapter in chapters
        )

        await clear_previous(session, lecture)
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
        await session.flush()
        await cache.clear()
    finally:
        await cache.close()
