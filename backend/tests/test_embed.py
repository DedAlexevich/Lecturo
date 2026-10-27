import asyncio
import json

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import (
    EMBEDDING_DIM,
    Chapter,
    ChunkKind,
    Lecture,
    SearchChunk,
    SourceType,
    Summary,
    TranscriptSegment,
)
from app.pipeline import embed
from app.pipeline.embed import MAX_DESCRIPTION_CHARS, parse_descriptions, split_into_chunks
from app.providers.openai_compat import OpenAICompatibleError
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

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(texts)
        return await super().embed_documents(texts)


@pytest.fixture
def embeddings(monkeypatch) -> RecordingEmbeddings:
    provider = RecordingEmbeddings()
    monkeypatch.setattr(embed, "get_embeddings", lambda: provider)
    return provider


class DescribingLLM:
    def __init__(self) -> None:
        self.requests: list[list[str]] = []
        self.active = 0
        self.peak = 0
        self.fail = False

    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        chunks = json.loads(user)["chunks"]
        self.requests.append([chunk["text"] for chunk in chunks])
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        if self.fail:
            raise OpenAICompatibleError("нет ответа")
        return json.dumps(
            {
                "descriptions": [
                    {"id": chunk["id"], "text": f"О чём {chunk['text'][:12]}"} for chunk in chunks
                ]
            },
            ensure_ascii=False,
        )


@pytest.fixture(autouse=True)
def llm(monkeypatch) -> DescribingLLM:
    provider = DescribingLLM()
    monkeypatch.setattr(embed, "get_llm", lambda: provider)
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
            .order_by(SearchChunk.start, SearchChunk.id)
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


def test_summary_chunks_follow_headings():
    content = "Вводная часть.\n\n## Пределы\n\n**Предел** функции.\n\n### Ряды\n- `ряд` Тейлора"

    chunks = embed.summary_chunks(content)

    assert [(c.section, c.text) for c in chunks] == [
        (None, "Вводная часть."),
        (0, "Пределы\nПредел функции."),
        (1, "Ряды\n- ряд Тейлора"),
    ]
    assert all(c.kind == ChunkKind.summary and c.start is None for c in chunks)


def test_long_summary_section_is_split(monkeypatch):
    monkeypatch.setattr(embed, "MAX_SECTION_CHARS", 20)

    chunks = embed.summary_chunks("## Тема\nпервая строка\nвторая строка")

    assert [c.text for c in chunks] == ["Тема\nпервая строка", "вторая строка"]
    assert {c.section for c in chunks} == {0}


async def test_embed_indexes_chapters_and_summary(user, embeddings):
    lecture = await create_lecture(user, even_bounds(120, 10))
    async with SessionLocal() as session:
        session.add_all(
            [
                Chapter(
                    lecture_id=lecture.id,
                    idx=0,
                    start=0,
                    end=60,
                    title="Пределы",
                    summary="Определение предела",
                ),
                Chapter(lecture_id=lecture.id, idx=1, start=60, end=120, title="Ряды"),
                Summary(lecture_id=lecture.id, content_md="## Пределы\nТекст\n## Ряды\nЕщё"),
            ]
        )
        await session.commit()

    await run_embed(lecture.id)

    chunks = await load_chunks(lecture.id)
    by_kind = {kind: [c for c in chunks if c.kind == kind] for kind in ChunkKind}
    assert len(by_kind[ChunkKind.transcript]) == 2
    assert [(c.start, c.end, c.text) for c in by_kind[ChunkKind.chapter]] == [
        (0, 60, "Пределы\nОпределение предела"),
        (60, 120, "Ряды"),
    ]
    assert sorted((c.section, c.text) for c in by_kind[ChunkKind.summary]) == [
        (0, "Пределы\nТекст"),
        (1, "Ряды\nЕщё"),
    ]
    assert all(c.embedding is not None for c in chunks)


async def test_embed_describes_transcript_chunks(user, embeddings, llm):
    lecture = await create_lecture(user, even_bounds(120, 10))
    async with SessionLocal() as session:
        session.add(Chapter(lecture_id=lecture.id, idx=0, start=0, end=120, title=" Пределы "))
        session.add(Summary(lecture_id=lecture.id, content_md="## Пределы\nТекст"))
        await session.commit()

    await run_embed(lecture.id)

    chunks = await load_chunks(lecture.id)
    described = {kind: [c.description for c in chunks if c.kind == kind] for kind in ChunkKind}
    assert described[ChunkKind.transcript] == ["О чём слово 0 слов", "О чём слово 6 слов"]
    assert described[ChunkKind.chapter] == ["Пределы"]
    assert described[ChunkKind.summary] == [None]
    assert len(llm.requests) == 1


async def test_descriptions_go_in_limited_parallel_batches(user, embeddings, llm, monkeypatch):
    monkeypatch.setattr(embed, "DESCRIBE_BATCH_SIZE", 2)
    lecture = await create_lecture(user, even_bounds(600, 10))

    await run_embed(lecture.id)

    assert [len(batch) for batch in llm.requests] == [2, 2, 2, 2, 2]
    assert llm.peak == embed.DESCRIBE_CONCURRENCY
    assert all(c.description for c in await load_chunks(lecture.id))


async def test_llm_error_leaves_descriptions_empty(user, embeddings, llm):
    llm.fail = True
    lecture = await create_lecture(user, even_bounds(120, 10))

    await run_embed(lecture.id)

    chunks = await load_chunks(lecture.id)
    assert len(chunks) == 2
    assert all(c.description is None and c.embedding is not None for c in chunks)


async def test_repeated_embed_keeps_ready_descriptions(user, embeddings, llm):
    lecture = await create_lecture(user, even_bounds(120, 10))
    await run_embed(lecture.id)
    async with SessionLocal() as session:
        second = await session.scalar(
            select(SearchChunk).where(SearchChunk.lecture_id == lecture.id, SearchChunk.start == 60)
        )
        second.description = None
        await session.commit()
    llm.requests.clear()

    await run_embed(lecture.id)

    assert llm.requests == [[" ".join(f"слово {i}" for i in range(6, 12))]]
    assert [c.description for c in await load_chunks(lecture.id)] == [
        "О чём слово 0 слов",
        "О чём слово 6 слов",
    ]


def test_parse_descriptions_skips_bad_items_and_shortens():
    content = json.dumps(
        {
            "descriptions": [
                {"id": 2, "text": "  Ряд   Тейлора "},
                {"id": 5, "text": "лишний"},
                {"id": "1", "text": "не число"},
                {"id": 3, "text": "а" * 200},
                "мусор",
            ]
        }
    )

    descriptions = parse_descriptions(content, 3)

    assert descriptions[:2] == [None, "Ряд Тейлора"]
    assert len(descriptions[2]) == MAX_DESCRIPTION_CHARS
    assert descriptions[2].endswith("…")


def test_parse_descriptions_rejects_wrong_shape():
    with pytest.raises(ValueError):
        parse_descriptions('{"text": "что-то"}', 2)
