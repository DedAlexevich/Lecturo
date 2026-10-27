import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chapter, ChunkKind, Lecture, SearchChunk, Summary, TranscriptSegment
from app.pipeline.runner import Report
from app.pipeline.stages import load_segments, require_ai_transfer
from app.providers import get_embeddings

MIN_CHUNK_SECONDS = 30.0
MAX_CHUNK_SECONDS = 60.0
BATCH_SIZE = 32
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


async def embed(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    await require_ai_transfer(session, lecture)
    chunks = [
        *split_into_chunks(await load_segments(session, lecture)),
        *await load_section_chunks(session, lecture.id),
    ]
    embeddings = get_embeddings()
    vectors: list[list[float]] = []
    for offset in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[offset : offset + BATCH_SIZE]
        vectors.extend(await embeddings.embed_documents([chunk.text for chunk in batch]))
        await report(len(vectors) / len(chunks))
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
        embedding=embedding,
    )


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
