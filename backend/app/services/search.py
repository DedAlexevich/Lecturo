import logging
import math
import re
import uuid
from collections.abc import Collection
from typing import Any

from sqlalchemy import ColumnElement, Text, cast, func, literal, select, text
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chapter, ChunkKind, Lecture, SearchChunk, TranscriptSegment
from app.providers import get_embeddings
from app.providers.openai_compat import OpenAICompatibleError
from app.schemas.search import SearchHit

logger = logging.getLogger(__name__)

CANDIDATES = 50
LIMIT = 20
MIN_PREFIX_LENGTH = 4
MIN_SIMILARITY = 0.2
MARGIN = 0.08
KEYWORD_BONUS = 0.03
NEIGHBOR_GAP = 10.0
PINPOINTED_MOMENTS = 3
MAX_SEGMENT_EMBEDDINGS = 16
CONTEXT_SECONDS = 30.0
LEXEME_PATTERN = re.compile(r"'((?:[^']|'')+)'")


async def embed_query(q: str) -> list[float] | None:
    try:
        vector = await get_embeddings().embed_query(q)
    except OpenAICompatibleError:
        logger.exception("Не удалось получить эмбеддинг запроса, ищем только по тексту")
        return None
    return vector


class Moment:
    def __init__(self, chunk: SearchChunk, score: float) -> None:
        self.best = chunk
        self.best_score = score
        self.score = score
        self.start = chunk.start
        self.end = chunk.end
        self.at = chunk.start
        self.text = chunk.text

    @property
    def lecture_id(self) -> uuid.UUID:
        return self.best.lecture_id

    def absorb(self, chunk: SearchChunk, score: float) -> None:
        self.score = max(self.score, score)
        if chunk.kind != self.best.kind:
            return
        if score > self.best_score:
            self.best, self.best_score = chunk, score
            self.at, self.text = chunk.start, chunk.text
        if self.end is not None and chunk.end is not None:
            self.end = max(self.end, chunk.end)

    def overlaps(self, chunk: SearchChunk) -> bool:
        return (
            self.lecture_id == chunk.lecture_id
            and self.start is not None
            and self.end is not None
            and chunk.start is not None
            and chunk.end is not None
            and self.start < chunk.end
            and chunk.start < self.end
        )


async def semantic_search(
    session: AsyncSession, scope: ColumnElement[bool], q: str, vector: list[float] | None
) -> list[SearchHit]:
    query = await build_tsquery(session, q)
    keyword = await fulltext_ranks(session, scope, query) if query is not None else {}
    if vector is None:
        scores = keyword
    else:
        candidates = set(keyword) | set(await vector_ids(session, scope, vector))
        scores = relevant(await similarities(session, candidates, vector), keyword.keys())
    if not scores:
        return []
    rows = (
        await session.execute(
            select(SearchChunk, Lecture.title)
            .join(Lecture, Lecture.id == SearchChunk.lecture_id)
            .where(SearchChunk.id.in_(scores))
        )
    ).all()
    titles = {chunk.lecture_id: title for chunk, title in rows}
    moments = sorted(
        group_moments([chunk for chunk, _ in rows], scores),
        key=lambda moment: (moment.score, keyword.get(moment.best.id, 0.0)),
        reverse=True,
    )[:LIMIT]
    await pinpoint(session, moments, query, vector)
    chapters = await chapter_titles(session, moments)
    return [
        SearchHit(
            lecture_id=moment.lecture_id,
            lecture_title=titles[moment.lecture_id],
            kind=moment.best.kind,
            start=moment.at,
            end=moment.end,
            section=moment.best.section,
            text=moment.text,
            description=moment.best.description,
            chapter_title=chapter_at(chapters.get(moment.lecture_id, []), moment.at),
            score=moment.score,
        )
        for moment in moments
    ]


async def chapter_titles(
    session: AsyncSession, moments: list[Moment]
) -> dict[uuid.UUID, list[Chapter]]:
    lecture_ids = {moment.lecture_id for moment in moments if moment.at is not None}
    if not lecture_ids:
        return {}
    chapters: dict[uuid.UUID, list[Chapter]] = {}
    for chapter in await session.scalars(
        select(Chapter).where(Chapter.lecture_id.in_(lecture_ids)).order_by(Chapter.start)
    ):
        chapters.setdefault(chapter.lecture_id, []).append(chapter)
    return chapters


def chapter_at(chapters: list[Chapter], at: float | None) -> str | None:
    if at is None:
        return None
    current = None
    for chapter in chapters:
        if chapter.start > at:
            break
        current = chapter
    if current is None or current.end < at:
        return None
    return current.title.strip() or None


def group_moments(chunks: list[SearchChunk], scores: dict[int, float]) -> list[Moment]:
    timed = sorted(
        (chunk for chunk in chunks if chunk.start is not None and chunk.end is not None),
        key=lambda chunk: (str(chunk.lecture_id), chunk.start),
    )
    moments = merge_neighbors(
        [chunk for chunk in timed if chunk.kind == ChunkKind.transcript], scores
    )
    unmatched: list[SearchChunk] = []
    for chunk in timed:
        if chunk.kind == ChunkKind.transcript:
            continue
        overlapping = [moment for moment in moments if moment.overlaps(chunk)]
        if overlapping:
            max(overlapping, key=lambda moment: moment.score).absorb(chunk, scores[chunk.id])
        else:
            unmatched.append(chunk)
    moments.extend(merge_neighbors(unmatched, scores))
    sections: dict[tuple[uuid.UUID, int | None], Moment] = {}
    for chunk in chunks:
        if chunk.start is not None and chunk.end is not None:
            continue
        if chunk.kind != ChunkKind.summary:
            moments.append(Moment(chunk, scores[chunk.id]))
        elif (key := (chunk.lecture_id, chunk.section)) in sections:
            sections[key].absorb(chunk, scores[chunk.id])
        else:
            sections[key] = Moment(chunk, scores[chunk.id])
            moments.append(sections[key])
    return moments


def merge_neighbors(chunks: list[SearchChunk], scores: dict[int, float]) -> list[Moment]:
    moments: list[Moment] = []
    for chunk in chunks:
        last = moments[-1] if moments else None
        if (
            last is not None
            and last.lecture_id == chunk.lecture_id
            and last.end is not None
            and chunk.start is not None
            and chunk.start <= last.end + NEIGHBOR_GAP
        ):
            last.absorb(chunk, scores[chunk.id])
        else:
            moments.append(Moment(chunk, scores[chunk.id]))
    return moments


async def pinpoint(
    session: AsyncSession,
    moments: list[Moment],
    query: ColumnElement[Any] | None,
    vector: list[float] | None,
) -> None:
    targets = [
        moment
        for moment in moments
        if moment.best.kind == ChunkKind.transcript and moment.start is not None
    ][:PINPOINTED_MOMENTS]
    spans = [await moment_segments(session, moment, query) for moment in targets]
    candidates = [
        narrow(
            [segment for segment in span if moment.best.start <= segment[0].start < moment.best.end]
        )
        for moment, span in zip(targets, spans, strict=True)
    ]
    texts = [segment.text for options in candidates if len(options) > 1 for segment, _ in options]
    closeness = iter(await segment_closeness(texts[:MAX_SEGMENT_EMBEDDINGS], vector))
    for moment, span, options in zip(targets, spans, candidates, strict=True):
        if not options:
            continue
        scored = [
            (
                (next(closeness, 0.0) if len(options) > 1 else 0.0)
                + (KEYWORD_BONUS if matched else 0.0),
                segment,
            )
            for segment, matched in options
        ]
        best = max(scored, key=lambda pair: pair[0])[1]
        moment.at = best.start
        moment.text = " ".join(
            segment.text.strip()
            for segment, _ in span
            if best.start <= segment.start < best.start + CONTEXT_SECONDS
        )


def narrow(
    options: list[tuple[TranscriptSegment, bool]],
) -> list[tuple[TranscriptSegment, bool]]:
    matched = [option for option in options if option[1]]
    return matched or options


async def moment_segments(
    session: AsyncSession, moment: Moment, query: ColumnElement[Any] | None
) -> list[tuple[TranscriptSegment, bool]]:
    matched = (
        func.to_tsvector(literal("russian", REGCONFIG), TranscriptSegment.text).op("@@")(query)
        if query is not None
        else literal(False)
    )
    rows = await session.execute(
        select(TranscriptSegment, matched)
        .where(
            TranscriptSegment.lecture_id == moment.lecture_id,
            TranscriptSegment.start >= moment.start,
            TranscriptSegment.start < moment.end,
            func.trim(TranscriptSegment.text) != "",
        )
        .order_by(TranscriptSegment.start, TranscriptSegment.idx)
    )
    return [(segment, bool(flag)) for segment, flag in rows]


async def segment_closeness(texts: list[str], vector: list[float] | None) -> list[float]:
    if vector is None or not texts:
        return [0.0] * len(texts)
    try:
        embedded = await get_embeddings().embed_documents(texts)
    except OpenAICompatibleError:
        logger.exception("Не удалось получить эмбеддинги сегментов, таймкод по словам")
        return [0.0] * len(texts)
    return [cosine(item, vector) for item in embedded]


def cosine(left: list[float], right: list[float]) -> float:
    norm = math.hypot(*left) * math.hypot(*right)
    return sum(a * b for a, b in zip(left, right, strict=True)) / norm if norm else 0.0


def relevant(similarity: dict[int, float], keyword: Collection[int]) -> dict[int, float]:
    scores = {
        chunk_id: value + (KEYWORD_BONUS if chunk_id in keyword else 0.0)
        for chunk_id, value in similarity.items()
    }
    threshold = max(scores.values(), default=0.0) - MARGIN
    kept = {
        chunk_id: score
        for chunk_id, score in scores.items()
        if score >= threshold and (chunk_id in keyword or similarity[chunk_id] >= MIN_SIMILARITY)
    }
    for chunk_id in keyword:
        if chunk_id not in similarity:
            kept[chunk_id] = MIN_SIMILARITY + KEYWORD_BONUS
    return kept


async def similarities(
    session: AsyncSession, ids: Collection[int], vector: list[float]
) -> dict[int, float]:
    if not ids:
        return {}
    similarity = 1 - SearchChunk.embedding.cosine_distance(vector)
    rows = await session.execute(
        select(SearchChunk.id, similarity).where(
            SearchChunk.id.in_(ids), SearchChunk.embedding.is_not(None)
        )
    )
    return {chunk_id: float(value) for chunk_id, value in rows}


async def build_tsquery(session: AsyncSession, q: str) -> ColumnElement[Any] | None:
    stemmed = await session.scalar(
        select(cast(func.websearch_to_tsquery(literal("russian", REGCONFIG), q), Text))
    )
    if not stemmed:
        return None
    return func.to_tsquery(literal("simple", REGCONFIG), add_prefixes(stemmed))


async def fulltext_ranks(
    session: AsyncSession, scope: ColumnElement[bool], query: ColumnElement[Any]
) -> dict[int, float]:
    rank = func.ts_rank_cd(SearchChunk.tsv, query)
    rows = await session.execute(
        select(SearchChunk.id, rank)
        .where(scope, SearchChunk.tsv.op("@@")(query))
        .order_by(rank.desc(), SearchChunk.id)
        .limit(CANDIDATES)
    )
    return {chunk_id: float(value) for chunk_id, value in rows}


def add_prefixes(tsquery: str) -> str:
    def prefix(match: re.Match[str]) -> str:
        lexeme = match.group(1).replace("''", "'")
        return f"{match.group(0)}:*" if len(lexeme) >= MIN_PREFIX_LENGTH else match.group(0)

    return LEXEME_PATTERN.sub(prefix, tsquery)


async def vector_ids(
    session: AsyncSession, scope: ColumnElement[bool], vector: list[float]
) -> list[int]:
    await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    rows = await session.scalars(
        select(SearchChunk.id)
        .where(scope, SearchChunk.embedding.is_not(None))
        .order_by(SearchChunk.embedding.cosine_distance(vector), SearchChunk.id)
        .limit(CANDIDATES)
    )
    return list(rows)
