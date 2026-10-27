import logging
import re
from collections.abc import Collection

from sqlalchemy import ColumnElement, Text, cast, func, literal, select, text
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lecture, SearchChunk
from app.providers import get_embeddings
from app.providers.openai_compat import OpenAICompatibleError
from app.schemas.search import SearchHit

logger = logging.getLogger(__name__)

CANDIDATES = 50
LIMIT = 20
MIN_PREFIX_LENGTH = 4
MIN_SIMILARITY = 0.2
MARGIN = 0.15
KEYWORD_BONUS = 0.03
LEXEME_PATTERN = re.compile(r"'((?:[^']|'')+)'")


async def embed_query(q: str) -> list[float] | None:
    try:
        vector = await get_embeddings().embed_query(q)
    except OpenAICompatibleError:
        logger.exception("Не удалось получить эмбеддинг запроса, ищем только по тексту")
        return None
    return vector


async def semantic_search(
    session: AsyncSession, scope: ColumnElement[bool], q: str, vector: list[float] | None
) -> list[SearchHit]:
    keyword = await fulltext_ranks(session, scope, q)
    if vector is None:
        scores = keyword
    else:
        candidates = set(keyword) | set(await vector_ids(session, scope, vector))
        scores = relevant(await similarities(session, candidates, vector), keyword.keys())
    top = sorted(
        scores, key=lambda chunk_id: (scores[chunk_id], keyword.get(chunk_id, 0.0)), reverse=True
    )[:LIMIT]
    if not top:
        return []
    rows = await session.execute(
        select(SearchChunk, Lecture.title)
        .join(Lecture, Lecture.id == SearchChunk.lecture_id)
        .where(SearchChunk.id.in_(top))
    )
    hits = {
        chunk.id: SearchHit(
            lecture_id=chunk.lecture_id,
            lecture_title=title,
            kind=chunk.kind,
            start=chunk.start,
            end=chunk.end,
            section=chunk.section,
            text=chunk.text,
            score=scores[chunk.id],
        )
        for chunk, title in rows
    }
    return [hits[chunk_id] for chunk_id in top]


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


async def fulltext_ranks(
    session: AsyncSession, scope: ColumnElement[bool], q: str
) -> dict[int, float]:
    stemmed = await session.scalar(
        select(cast(func.websearch_to_tsquery(literal("russian", REGCONFIG), q), Text))
    )
    if not stemmed:
        return {}
    query = func.to_tsquery(literal("simple", REGCONFIG), add_prefixes(stemmed))
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
