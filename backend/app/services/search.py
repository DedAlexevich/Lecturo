from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, literal, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lecture, SearchChunk
from app.providers import get_embeddings
from app.schemas.search import SearchHit

RRF_K = 60
CANDIDATES = 50
LIMIT = 20


async def hybrid_search(
    session: AsyncSession, scope: ColumnElement[bool], q: str
) -> list[SearchHit]:
    ranked_lists = [
        await fulltext_ids(session, scope, q),
        await vector_ids(session, scope, q),
    ]
    scores = rrf(ranked_lists)
    top = sorted(scores, key=scores.__getitem__, reverse=True)[:LIMIT]
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
            start=chunk.start,
            end=chunk.end,
            text=chunk.text,
            score=scores[chunk.id],
        )
        for chunk, title in rows
    }
    return [hits[chunk_id] for chunk_id in top]


async def fulltext_ids(session: AsyncSession, scope: ColumnElement[bool], q: str) -> list[int]:
    query = func.websearch_to_tsquery(literal("russian", REGCONFIG), q)
    rows = await session.scalars(
        select(SearchChunk.id)
        .where(scope, SearchChunk.tsv.op("@@")(query))
        .order_by(func.ts_rank_cd(SearchChunk.tsv, query).desc(), SearchChunk.id)
        .limit(CANDIDATES)
    )
    return list(rows)


async def vector_ids(session: AsyncSession, scope: ColumnElement[bool], q: str) -> list[int]:
    [vector] = await get_embeddings().embed([q])
    rows = await session.scalars(
        select(SearchChunk.id)
        .where(scope, SearchChunk.embedding.is_not(None))
        .order_by(SearchChunk.embedding.cosine_distance(vector), SearchChunk.id)
        .limit(CANDIDATES)
    )
    return list(rows)


def rrf(ranked_lists: Sequence[Sequence[int]]) -> dict[int, float]:
    scores: dict[int, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] += 1 / (RRF_K + rank)
    return dict(scores)
