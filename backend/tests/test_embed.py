import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import EMBEDDING_DIM, Lecture, SearchChunk, SourceType, TranscriptSegment
from app.pipeline import embed
from app.pipeline.embed import split_into_chunks
from app.providers.stub import StubEmbeddings


def make_segments(bounds, text="слово") -> list[TranscriptSegment]:
    return [
        TranscriptSegment(idx=idx, start=start, end=end, text=f"{text} {idx}")
        for idx, (start, end) in enumerate(bounds)
    ]


def even_bounds(total: float, step: float) -> list[tuple[float, float]]:
    count = int(total // step)
    return [(i * step, (i + 1) * step) for i in range(count)]


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        ([], []),
        ([(0, 20), (20, 40), (40, 59)], [(0, 59)]),
        ([(0, 30), (30, 61), (61, 90)], [(0, 30), (30, 90)]),
        (even_bounds(70, 10), [(0, 40), (40, 70)]),
        ([(0, 10), (10, 95), (95, 100)], [(0, 10), (10, 95), (95, 100)]),
    ],
)
def test_split_into_chunks(bounds, expected):
    chunks = split_into_chunks(make_segments(bounds))
    assert [(c.start, c.end) for c in chunks] == expected


@pytest.mark.parametrize("step", [4.5, 7.0, 13.0, 29.0])
def test_chunks_stay_between_30_and_60_seconds(step):
    chunks = split_into_chunks(make_segments(even_bounds(600, step)))

    assert all(30 <= c.end - c.start <= 60 for c in chunks)
    assert chunks[0].start == 0
    assert all(a.end == b.start for a, b in zip(chunks, chunks[1:], strict=False))


def test_chunk_text_joins_segments_and_skips_blank_ones():
    segments = [
        TranscriptSegment(idx=0, start=0, end=5, text="Первая фраза."),
        TranscriptSegment(idx=1, start=5, end=10, text="  "),
        TranscriptSegment(idx=2, start=10, end=15, text=" Вторая фраза. "),
    ]

    [chunk] = split_into_chunks(segments)

    assert chunk.text == "Первая фраза. Вторая фраза."
    assert (chunk.start, chunk.end) == (0, 15)


class RecordingEmbeddings(StubEmbeddings):
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(texts)
        return await super().embed(texts)


@pytest.fixture
def embeddings(monkeypatch) -> RecordingEmbeddings:
    provider = RecordingEmbeddings()
    monkeypatch.setattr(embed, "get_embeddings", lambda: provider)
    return provider


async def create_lecture(user, bounds, text="слово") -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title="Матанализ", source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        for segment in make_segments(bounds, text):
            segment.lecture_id = lecture.id
            session.add(segment)
        await session.commit()
        return lecture


async def run_embed(lecture_id) -> list[float]:
    progress: list[float] = []

    async def report(value: float) -> None:
        progress.append(value)

    async with SessionLocal() as session:
        lecture = await session.get(Lecture, lecture_id)
        await embed.embed(session, lecture, report)
        await session.commit()
    return progress


async def load_chunks(lecture_id) -> list[SearchChunk]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(SearchChunk)
            .where(SearchChunk.lecture_id == lecture_id)
            .order_by(SearchChunk.start)
        )
        return list(rows)


async def test_embed_saves_chunks_with_vectors(user, embeddings):
    lecture = await create_lecture(user, even_bounds(300, 10))

    await run_embed(lecture.id)

    chunks = await load_chunks(lecture.id)
    assert [(c.start, c.end) for c in chunks] == [(i * 60.0, (i + 1) * 60.0) for i in range(5)]
    assert all(len(c.embedding) == EMBEDDING_DIM for c in chunks)
    assert chunks[0].text.startswith("слово 0 слово 1")


async def test_embed_sends_texts_in_batches_and_reports_progress(user, embeddings, monkeypatch):
    monkeypatch.setattr(embed, "BATCH_SIZE", 2)
    lecture = await create_lecture(user, even_bounds(300, 10))

    progress = await run_embed(lecture.id)

    assert [len(batch) for batch in embeddings.batches] == [2, 2, 1]
    assert progress == [0.4, 0.8, 1.0]
    assert len(await load_chunks(lecture.id)) == 5


async def test_repeated_embed_replaces_chunks(user, embeddings):
    lecture = await create_lecture(user, even_bounds(120, 10), text="старое")
    await run_embed(lecture.id)

    async with SessionLocal() as session:
        for segment in await session.scalars(
            select(TranscriptSegment).where(TranscriptSegment.lecture_id == lecture.id)
        ):
            segment.text = segment.text.replace("старое", "новое")
        await session.commit()
    await run_embed(lecture.id)

    chunks = await load_chunks(lecture.id)
    assert len(chunks) == 2
    assert all(c.text.startswith("новое") for c in chunks)


async def test_embed_without_segments_clears_chunks(user, embeddings):
    lecture = await create_lecture(user, even_bounds(60, 10))
    await run_embed(lecture.id)
    async with SessionLocal() as session:
        for segment in await session.scalars(
            select(TranscriptSegment).where(TranscriptSegment.lecture_id == lecture.id)
        ):
            await session.delete(segment)
        await session.commit()

    await run_embed(lecture.id)

    assert await load_chunks(lecture.id) == []
    assert embeddings.batches == [[" ".join(f"слово {i}" for i in range(6))]]
