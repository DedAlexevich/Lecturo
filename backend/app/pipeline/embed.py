import asyncio
import json
import logging
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chapter,
    ChunkKind,
    Lecture,
    SearchChunk,
    SourceType,
    Summary,
    TranscriptSegment,
)
from app.pipeline.runner import Report
from app.pipeline.stages import load_segments, require_ai_transfer
from app.pipeline.summarize import load_prompt, parse_json
from app.providers import LLM, get_embeddings, get_llm
from app.providers.openai_compat import OpenAICompatibleError

logger = logging.getLogger(__name__)

MIN_CHUNK_SECONDS = 30.0
MAX_CHUNK_SECONDS = 60.0
DESCRIBE_BATCH_SIZE = 25
DESCRIBE_CONCURRENCY = 3
MAX_DESCRIPTION_CHARS = 140
MAX_SECTION_CHARS = 1500
HEADING_PATTERN = re.compile(r"^#{1,4}\s+")
MARKUP_PATTERN = re.compile(r"[*`]")


@dataclass(frozen=True)
class Chunk:
    start: float | None
    end: float | None
    text: str
    kind: ChunkKind = ChunkKind.transcript
    section: int | None = None
    description: str | None = None


async def embed(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    await require_ai_transfer(session, lecture)
    local = lecture.processed_locally or lecture.source_type == SourceType.local
    chunks = await describe_chunks(
        None if local else get_llm(),
        [
            *split_into_chunks(await load_segments(session, lecture)),
            *await load_section_chunks(session, lecture.id),
        ],
        await known_descriptions(session, lecture.id),
    )
    texts = [chunk.text for chunk in chunks]
    vectors = await get_embeddings().embed_documents(texts) if texts else []
    await session.execute(delete(SearchChunk).where(SearchChunk.lecture_id == lecture.id))
    session.add_all(
        to_search_chunk(lecture.id, chunk, vector)
        for chunk, vector in zip(chunks, vectors, strict=True)
    )


def to_search_chunk(
    lecture_id: uuid.UUID, chunk: Chunk, embedding: list[float] | None = None
) -> SearchChunk:
    return SearchChunk(
        lecture_id=lecture_id,
        kind=chunk.kind,
        start=chunk.start,
        end=chunk.end,
        section=chunk.section,
        text=chunk.text,
        description=chunk.description,
        embedding=embedding,
    )


DescriptionKey = tuple[ChunkKind, float | None, str]


async def known_descriptions(
    session: AsyncSession, lecture_id: uuid.UUID
) -> dict[DescriptionKey, str]:
    rows = await session.execute(
        select(
            SearchChunk.kind, SearchChunk.start, SearchChunk.text, SearchChunk.description
        ).where(SearchChunk.lecture_id == lecture_id, SearchChunk.description.is_not(None))
    )
    return {(kind, start, text): description for kind, start, text, description in rows}


async def describe_chunks(
    llm: LLM | None, chunks: list[Chunk], known: dict[DescriptionKey, str]
) -> list[Chunk]:
    chunks = [
        replace(chunk, description=known.get((chunk.kind, chunk.start, chunk.text)))
        if chunk.kind == ChunkKind.transcript
        else chunk
        for chunk in chunks
    ]
    if llm is None:
        return chunks
    pending = [
        index
        for index, chunk in enumerate(chunks)
        if chunk.kind == ChunkKind.transcript and chunk.description is None
    ]
    batches = [
        pending[offset : offset + DESCRIBE_BATCH_SIZE]
        for offset in range(0, len(pending), DESCRIBE_BATCH_SIZE)
    ]
    semaphore = asyncio.Semaphore(DESCRIBE_CONCURRENCY)
    results = await asyncio.gather(
        *(describe_batch(llm, semaphore, [chunks[index] for index in batch]) for batch in batches)
    )
    for batch, descriptions in zip(batches, results, strict=True):
        for index, description in zip(batch, descriptions, strict=True):
            chunks[index] = replace(chunks[index], description=description)
    return chunks


async def describe_batch(
    llm: LLM, semaphore: asyncio.Semaphore, batch: list[Chunk]
) -> list[str | None]:
    request = json.dumps(
        {"chunks": [{"id": number, "text": chunk.text} for number, chunk in enumerate(batch, 1)]},
        ensure_ascii=False,
    )
    try:
        async with semaphore:
            content = await llm.complete(load_prompt("moments"), request, json_mode=True)
        return parse_descriptions(content, len(batch))
    except (OpenAICompatibleError, ValueError):
        logger.warning("Не удалось получить описания фрагментов для поиска", exc_info=True)
        return [None] * len(batch)


def parse_descriptions(content: str, count: int) -> list[str | None]:
    items = parse_json(content).get("descriptions")
    if not isinstance(items, list):
        raise ValueError("LLM вернула описания не того вида")
    descriptions: list[str | None] = [None] * count
    for item in items:
        if not isinstance(item, dict):
            continue
        number, text = item.get("id"), item.get("text")
        if isinstance(number, int) and 1 <= number <= count and isinstance(text, str):
            descriptions[number - 1] = shorten(text)
    return descriptions


def shorten(text: str) -> str | None:
    text = " ".join(text.split())
    if len(text) <= MAX_DESCRIPTION_CHARS:
        return text or None
    return text[: MAX_DESCRIPTION_CHARS - 1].rstrip() + "…"


async def load_section_chunks(session: AsyncSession, lecture_id: uuid.UUID) -> list[Chunk]:
    chapters = await session.scalars(
        select(Chapter).where(Chapter.lecture_id == lecture_id).order_by(Chapter.idx)
    )
    summary = await session.scalar(
        select(Summary.content_md).where(Summary.lecture_id == lecture_id)
    )
    return [*chapter_chunks(chapters), *summary_chunks(summary or "")]


def chapter_chunks(chapters: Iterable[Chapter]) -> list[Chunk]:
    return [
        Chunk(
            start=chapter.start,
            end=chapter.end,
            text=f"{chapter.title.strip()}\n{chapter.summary.strip()}".strip(),
            kind=ChunkKind.chapter,
            description=shorten(chapter.title),
        )
        for chapter in chapters
    ]


def summary_chunks(content_md: str) -> list[Chunk]:
    sections: list[tuple[int | None, list[str]]] = [(None, [])]
    for line in content_md.replace("\r\n", "\n").split("\n"):
        if HEADING_PATTERN.match(line.strip()):
            sections.append((len(sections) - 1, []))
        if plain := MARKUP_PATTERN.sub("", HEADING_PATTERN.sub("", line.strip())).strip():
            sections[-1][1].append(plain)
    return [
        Chunk(start=None, end=None, text=piece, kind=ChunkKind.summary, section=section)
        for section, lines in sections
        for piece in join_lines(lines)
    ]


def join_lines(lines: list[str]) -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) > MAX_SECTION_CHARS:
            pieces.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        pieces.append("\n".join(current))
    return pieces


def split_into_chunks(segments: Sequence[TranscriptSegment]) -> list[Chunk]:
    groups: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []
    for segment in segments:
        if not segment.text.strip():
            continue
        if current and segment.end - current[0].start > MAX_CHUNK_SECONDS:
            groups.append(current)
            current = []
        current.append(segment)
    if current:
        groups.append(current)
    if len(groups) > 1:
        balance_tail(groups[-2], groups[-1])
    return [
        Chunk(
            start=group[0].start,
            end=group[-1].end,
            text=" ".join(segment.text.strip() for segment in group),
        )
        for group in groups
    ]


def balance_tail(previous: list[TranscriptSegment], last: list[TranscriptSegment]) -> None:
    while len(previous) > 1 and span(last) < MIN_CHUNK_SECONDS:
        moved = previous[-1]
        if (
            span(previous[:-1]) < MIN_CHUNK_SECONDS
            or last[-1].end - moved.start > MAX_CHUNK_SECONDS
        ):
            return
        last.insert(0, previous.pop())


def span(group: Sequence[TranscriptSegment]) -> float:
    return group[-1].end - group[0].start
