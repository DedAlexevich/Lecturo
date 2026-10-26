from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chapter, Lecture, SearchChunk, Summary, TranscriptSegment
from app.pipeline.runner import Report
from app.providers import get_embeddings, get_llm, get_speech_to_text

CHUNK_SECONDS = 60.0


async def transcribe(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    segments = await get_speech_to_text().transcribe(
        Path(lecture.audio_path or ""), lecture.language
    )
    await session.execute(
        delete(TranscriptSegment).where(TranscriptSegment.lecture_id == lecture.id)
    )
    session.add_all(
        TranscriptSegment(lecture_id=lecture.id, idx=idx, start=s.start, end=s.end, text=s.text)
        for idx, s in enumerate(segments)
    )
    if lecture.duration_sec is None and segments:
        lecture.duration_sec = segments[-1].end


async def summarize(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    segments = await load_segments(session, lecture)
    text = " ".join(s.text for s in segments)
    content = await get_llm().complete("Составь конспект лекции.", text)
    await session.execute(delete(Chapter).where(Chapter.lecture_id == lecture.id))
    await session.execute(delete(Summary).where(Summary.lecture_id == lecture.id))
    session.add(Summary(lecture_id=lecture.id, content_md=content))
    if segments:
        session.add(
            Chapter(
                lecture_id=lecture.id,
                idx=0,
                start=segments[0].start,
                end=segments[-1].end,
                title=lecture.title,
                summary=content,
            )
        )


async def embed(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    chunks = split_into_chunks(await load_segments(session, lecture))
    vectors = await get_embeddings().embed([text for _, _, text in chunks])
    await session.execute(delete(SearchChunk).where(SearchChunk.lecture_id == lecture.id))
    session.add_all(
        SearchChunk(lecture_id=lecture.id, start=start, end=end, text=text, embedding=vector)
        for (start, end, text), vector in zip(chunks, vectors, strict=True)
    )


async def load_segments(session: AsyncSession, lecture: Lecture) -> list[TranscriptSegment]:
    rows = await session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.lecture_id == lecture.id)
        .order_by(TranscriptSegment.idx)
    )
    return list(rows)


def split_into_chunks(segments: list[TranscriptSegment]) -> list[tuple[float, float, str]]:
    chunks: list[tuple[float, float, str]] = []
    current: list[TranscriptSegment] = []
    for segment in segments:
        if current and segment.end - current[0].start > CHUNK_SECONDS:
            chunks.append((current[0].start, current[-1].end, " ".join(s.text for s in current)))
            current = []
        current.append(segment)
    if current:
        chunks.append((current[0].start, current[-1].end, " ".join(s.text for s in current)))
    return chunks
