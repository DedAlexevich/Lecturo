import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.courses import get_own_course
from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep
from app.models import ChunkKind, Lecture, SearchChunk, course_lectures
from app.schemas.search import SearchHit
from app.services.rate_limit import enforce_rate_limit
from app.services.search import embed_query, semantic_search

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "",
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Слишком много поисковых запросов"}
    },
)
async def search(
    user: CurrentUser,
    session: SessionDep,
    q: str = Query(min_length=2, max_length=200),
    lecture_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
) -> list[SearchHit]:
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Запрос слишком короткий")
    if lecture_id is not None and course_id is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Укажите либо лекцию, либо курс")
    settings = get_settings()
    await enforce_rate_limit(
        settings.redis_url,
        f"rate:search:{user.id}",
        settings.search_rate_limit,
        settings.search_rate_window_seconds,
        "Слишком много поисковых запросов, попробуйте через минуту",
    )
    vector = await embed_query(q)
    if lecture_id is None and course_id is None:
        scope = SearchChunk.lecture_id.in_(select(Lecture.id).where(Lecture.owner_id == user.id))
        return await semantic_search(session, scope, q, vector)
    if lecture_id is not None:
        found = await session.scalar(
            select(Lecture.id).where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
        )
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
        scope = SearchChunk.lecture_id == lecture_id
    else:
        await get_own_course(session, course_id, user)
        scope = SearchChunk.lecture_id.in_(
            select(course_lectures.c.lecture_id)
            .join(Lecture, Lecture.id == course_lectures.c.lecture_id)
            .where(course_lectures.c.course_id == course_id, Lecture.owner_id == user.id)
        )
    transcript_only = scope & (SearchChunk.kind == ChunkKind.transcript)
    return await semantic_search(session, transcript_only, q, vector)
