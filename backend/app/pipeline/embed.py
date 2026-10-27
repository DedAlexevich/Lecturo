from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lecture, SearchChunk, TranscriptSegment
from app.pipeline.runner import Report
from app.pipeline.stages import load_segments, require_ai_transfer
from app.providers import get_embeddings

MIN_CHUNK_SECONDS = 30.0
MAX_CHUNK_SECONDS = 60.0
BATCH_SIZE = 32


@dataclass(frozen=True)
class Chunk:
    start: float
    end: float
    text: str


async def embed(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    await require_ai_transfer(session, lecture)
    chunks = split_into_chunks(await load_segments(session, lecture))
    embeddings = get_embeddings()
    vectors: list[list[float]] = []
    for offset in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[offset : offset + BATCH_SIZE]
        vectors.extend(await embeddings.embed_documents([chunk.text for chunk in batch]))
        await report(len(vectors) / len(chunks))
    await session.execute(delete(SearchChunk).where(SearchChunk.lecture_id == lecture.id))
    session.add_all(
        SearchChunk(
            lecture_id=lecture.id,
            start=chunk.start,
            end=chunk.end,
            text=chunk.text,
            embedding=vector,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    )


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
