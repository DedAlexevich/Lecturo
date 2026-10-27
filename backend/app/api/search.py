import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.core.deps import CurrentUser, SessionDep
from app.models import Course, Lecture, SearchChunk, course_lectures
from app.schemas.search import SearchHit
from app.services.search import hybrid_search

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def search(
    user: CurrentUser,
    session: SessionDep,
    q: str = Query(min_length=2, max_length=200),
    lecture_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
) -> list[SearchHit]:
    if (lecture_id is None) == (course_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Укажите либо лекцию, либо курс")
    if lecture_id is not None:
        found = await session.scalar(
            select(Lecture.id).where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
        )
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
        scope = SearchChunk.lecture_id == lecture_id
    else:
        found = await session.scalar(
            select(Course.id).where(Course.id == course_id, Course.owner_id == user.id)
        )
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Курс не найден")
        scope = SearchChunk.lecture_id.in_(
            select(course_lectures.c.lecture_id)
            .join(Lecture, Lecture.id == course_lectures.c.lecture_id)
            .where(course_lectures.c.course_id == course_id, Lecture.owner_id == user.id)
        )
    return await hybrid_search(session, scope, q.strip())
