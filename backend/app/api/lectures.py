import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Response, status
from redis.exceptions import RedisError
from sqlalchemy import delete, exists, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.api.courses import get_own_course
from app.core.deps import CurrentUser, RequireSubscription, SessionDep
from app.core.errors import not_ready
from app.models import (
    Lecture,
    LectureStatus,
    ProcessingStep,
    ShareLink,
    SourceType,
    StepStatus,
    course_lectures,
)
from app.pipeline.download import LinkError, inspect_link
from app.pipeline.events import publish_status
from app.pipeline.tasks import cancel_lecture_job, enqueue_lecture
from app.pipeline.video_access import is_valid_signature, signed_video_url
from app.schemas.lecture import (
    LectureDetail,
    LectureOut,
    LectureStatusOut,
    LectureUpdate,
    LinkIn,
    QuizOut,
)
from app.services import quota
from app.services.account import lecture_files, remove_files
from app.services.consents import require_ai_transfer_consent

router = APIRouter(prefix="/lectures", tags=["lectures"])

QUEUE_UNAVAILABLE = "Очередь недоступна, попробуйте позже"
VIDEO_FORBIDDEN = "Нет доступа к видео"


async def add_to_course(session: AsyncSession, course_id: uuid.UUID, lecture_id: uuid.UUID) -> None:
    next_position = (
        select(func.coalesce(func.max(course_lectures.c.position) + 1, 0))
        .where(course_lectures.c.course_id == course_id)
        .scalar_subquery()
    )
    await session.execute(
        insert(course_lectures).values(
            course_id=course_id, lecture_id=lecture_id, position=next_position
        )
    )


@router.get("")
async def list_lectures(user: CurrentUser, session: SessionDep) -> list[LectureOut]:
    rows = await session.scalars(
        select(Lecture).where(Lecture.owner_id == user.id).order_by(Lecture.created_at.desc())
    )
    return [LectureOut.model_validate(row) for row in rows]


@router.get("/{lecture_id}")
async def get_lecture(
    lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> LectureDetail:
    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
        .options(
            selectinload(Lecture.steps),
            selectinload(Lecture.segments),
            selectinload(Lecture.chapters),
            selectinload(Lecture.summary),
        )
    )
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
    video_url = signed_video_url(lecture.id) if lecture.video_path else None
    return LectureDetail.model_validate(lecture).model_copy(update={"video_url": video_url})


@router.get("/{lecture_id}/video-access")
async def video_access(
    lecture_id: uuid.UUID,
    session: SessionDep,
    expires: int = 0,
    signature: str = "",
    share: str | None = None,
) -> Response:
    if not is_valid_signature(lecture_id, expires, signature, share):
        raise HTTPException(status.HTTP_403_FORBIDDEN, VIDEO_FORBIDDEN)
    query = select(Lecture.id).where(Lecture.id == lecture_id, Lecture.video_path.is_not(None))
    if share is not None:
        query = query.join(ShareLink, ShareLink.lecture_id == Lecture.id).where(
            ShareLink.token == share, ShareLink.revoked_at.is_(None)
        )
    if await session.scalar(query) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, VIDEO_FORBIDDEN)
    return Response(status_code=status.HTTP_200_OK)


@router.post("/link", status_code=status.HTTP_201_CREATED)
async def add_link(body: LinkIn, user: CurrentUser, session: SessionDep) -> LectureOut:
    require_ai_transfer_consent(user)
    await session.commit()
    url = str(body.url)
    try:
        link = await inspect_link(url)
    except LinkError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if body.course_id is not None:
        await get_own_course(session, body.course_id, user)

    lecture = Lecture(
        owner_id=user.id,
        title=(body.title or link.title or "Лекция по ссылке")[:300],
        source_type=SourceType.link,
        source_url=url,
        embed_url=link.embed_url,
        duration_sec=link.duration,
        status=LectureStatus.queued,
    )
    session.add(lecture)
    await session.flush()
    if body.course_id is not None:
        await add_to_course(session, body.course_id, lecture.id)
    waiting = await quota.hold_if_over_quota(session, user, lecture)
    await session.commit()
    await session.refresh(lecture)
    if waiting:
        await publish_status(lecture.id, user.id, lecture.status)
        return LectureOut.model_validate(lecture)

    try:
        await enqueue_lecture(lecture.id)
    except (OSError, RedisError) as error:
        lecture.status = LectureStatus.failed
        await session.commit()
        await publish_status(lecture.id, user.id, LectureStatus.failed, QUEUE_UNAVAILABLE)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error
    return LectureOut.model_validate(lecture)


@router.patch("/{lecture_id}")
async def update_lecture(
    lecture_id: uuid.UUID, body: LectureUpdate, user: CurrentUser, session: SessionDep
) -> LectureOut:
    lecture = await session.scalar(
        select(Lecture).where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
    )
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
    lecture.title = body.title
    await session.commit()
    await session.refresh(lecture)
    return LectureOut.model_validate(lecture)


@router.delete("/{lecture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lecture(lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
        .with_for_update()
    )
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
    started = await session.scalar(
        select(exists().where(ProcessingStep.lecture_id == lecture_id, ProcessingStep.attempts > 0))
    )
    if not started and lecture.status in (LectureStatus.queued, LectureStatus.waiting_quota):
        await quota.refund_lecture(session, lecture_id)
    files = lecture_files(lecture_id, [lecture.video_path, lecture.audio_path])
    await session.execute(delete(Lecture).where(Lecture.id == lecture_id))
    await session.commit()

    try:
        await cancel_lecture_job(lecture_id)
    except (OSError, RedisError):
        pass
    await asyncio.to_thread(remove_files, files)


@router.get("/{lecture_id}/status")
async def get_status(
    lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> LectureStatusOut:
    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
        .options(
            load_only(Lecture.id, Lecture.status, Lecture.queue_position),
            selectinload(Lecture.steps),
        )
    )
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
    return LectureStatusOut.model_validate(lecture)


@router.post("/{lecture_id}/retry")
async def retry(lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> LectureStatusOut:
    queued = await session.scalar(
        update(Lecture)
        .where(
            Lecture.id == lecture_id,
            Lecture.owner_id == user.id,
            Lecture.status == LectureStatus.failed,
        )
        .values(status=LectureStatus.queued)
        .returning(Lecture.id)
    )
    if queued is None:
        owned = await session.scalar(
            select(Lecture.id).where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
        )
        if owned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Перезапустить можно только упавшую обработку"
        )
    await session.execute(
        update(ProcessingStep)
        .where(ProcessingStep.lecture_id == lecture_id, ProcessingStep.status == StepStatus.failed)
        .values(status=StepStatus.pending, progress=0.0, error=None)
    )
    await session.commit()

    try:
        await enqueue_lecture(lecture_id)
    except (OSError, RedisError) as error:
        await session.execute(
            update(Lecture).where(Lecture.id == lecture_id).values(status=LectureStatus.failed)
        )
        await session.commit()
        await publish_status(lecture_id, user.id, LectureStatus.failed, QUEUE_UNAVAILABLE)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error

    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id)
        .options(selectinload(Lecture.steps))
        .execution_options(populate_existing=True)
    )
    return LectureStatusOut.model_validate(lecture)


@router.post("/{lecture_id}/quiz", status_code=status.HTTP_202_ACCEPTED)
async def create_quiz(lecture_id: uuid.UUID, user: RequireSubscription) -> None:
    not_ready()


@router.get("/{lecture_id}/quiz")
async def get_quiz(lecture_id: uuid.UUID, user: RequireSubscription) -> QuizOut:
    not_ready()
