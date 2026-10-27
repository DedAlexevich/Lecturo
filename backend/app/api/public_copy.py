import uuid
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Response, status
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.shares import SHARE_NOT_FOUND, get_active_share, is_confirmed, shared_with
from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep
from app.models import Course, Lecture, LectureStatus, ShareLink, User, course_lectures
from app.schemas.share import CopyConflictOut, CopyIn, CopyOut
from app.services.lecture_copy import (
    copy_course,
    copy_lecture,
    existing_copy_id,
    existing_course_copy_id,
)
from app.services.rate_limit import charge_budget, refund_budget

router = APIRouter(tags=["shares"])

COPY_WINDOW_SECONDS = 24 * 3600
LIMIT_MESSAGE = "Дневной лимит сохранения лекций исчерпан, попробуйте завтра"


def conflict(message: str, lecture_id: uuid.UUID | None, course_id: uuid.UUID | None):
    return HTTPException(
        status.HTTP_409_CONFLICT,
        {
            "message": message,
            "lecture_id": str(lecture_id) if lecture_id else None,
            "course_id": str(course_id) if course_id else None,
        },
    )


def require_can_copy(user: User) -> None:
    if not is_confirmed(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Подтвердите почту или привяжите Telegram, чтобы сохранять лекции",
        )
    if user.personal_data_accepted_at is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Для сохранения лекции нужно согласие на обработку данных"
        )


async def shared_ready_lecture(session: AsyncSession, token: str, lecture_id: uuid.UUID) -> Lecture:
    lecture = await session.scalar(
        select(Lecture).where(
            Lecture.id == lecture_id,
            Lecture.status == LectureStatus.ready,
            shared_with(token),
        )
    )
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SHARE_NOT_FOUND)
    return lecture


async def charge(user: User, amount: int) -> str:
    settings = get_settings()
    key = f"rate:public-copy:{user.id}"
    try:
        allowed = await charge_budget(
            settings.redis_url,
            key,
            amount,
            settings.public_copy_daily_limit,
            COPY_WINDOW_SECONDS,
        )
    except (OSError, RedisError) as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Сервис временно недоступен, попробуйте позже"
        ) from error
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, LIMIT_MESSAGE)
    return key


async def copy_single(
    session: AsyncSession, user: User, token: str, lecture_id: uuid.UUID, response: Response
) -> CopyOut:
    source = await shared_ready_lecture(session, token, lecture_id)
    if source.owner_id == user.id:
        raise conflict("Это ваша лекция", source.id, None)
    existing = await existing_copy_id(session, user.id, source.id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return CopyOut(lecture_id=existing, course_id=None, lecture_ids=[existing], created=False)
    key = await charge(user, 1)
    try:
        copy_id = await copy_lecture(session, source, user.id)
        await session.commit()
    except BaseException:
        await session.rollback()
        await refund_budget(get_settings().redis_url, key, 1)
        raise
    return CopyOut(lecture_id=copy_id, course_id=None, lecture_ids=[copy_id], created=True)


async def copy_whole_course(
    session: AsyncSession, user: User, share: ShareLink, response: Response
) -> CopyOut:
    course = await session.get(Course, share.course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SHARE_NOT_FOUND)
    if course.owner_id == user.id:
        raise conflict("Это ваш курс", None, course.id)
    existing = await existing_course_copy_id(session, user.id, course.id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        lecture_ids = list(
            await session.scalars(
                select(course_lectures.c.lecture_id)
                .where(course_lectures.c.course_id == existing)
                .order_by(course_lectures.c.position)
            )
        )
        return CopyOut(lecture_id=None, course_id=existing, lecture_ids=lecture_ids, created=False)
    lectures = list(
        await session.scalars(
            select(Lecture)
            .join(course_lectures, course_lectures.c.lecture_id == Lecture.id)
            .where(
                course_lectures.c.course_id == course.id,
                Lecture.status == LectureStatus.ready,
            )
            .order_by(course_lectures.c.position, course_lectures.c.added_at)
        )
    )
    if not lectures:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SHARE_NOT_FOUND)
    new_count = 0
    for lecture in lectures:
        if await existing_copy_id(session, user.id, lecture.id) is None:
            new_count += 1
    key = await charge(user, new_count) if new_count else None
    try:
        course_id, lecture_ids = await copy_course(session, course, lectures, user.id)
        await session.commit()
    except BaseException:
        await session.rollback()
        if key is not None:
            await refund_budget(get_settings().redis_url, key, new_count)
        raise
    return CopyOut(lecture_id=None, course_id=course_id, lecture_ids=lecture_ids, created=True)


@router.post(
    "/public/{token}/copy",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": CopyConflictOut}},
)
async def copy_shared(
    token: str,
    user: CurrentUser,
    session: SessionDep,
    response: Response,
    body: Annotated[CopyIn | None, Body()] = None,
) -> CopyOut:
    require_can_copy(user)
    share = await get_active_share(session, token)
    await session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"public-copy:{user.id}"},
    )
    lecture_id = share.lecture_id or (body.lecture_id if body else None)
    if lecture_id is not None:
        return await copy_single(session, user, token, lecture_id, response)
    return await copy_whole_course(session, user, share, response)
