import uuid
from datetime import datetime

from fastapi import HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdminAction,
    Lecture,
    LectureStatus,
    ProcessingStep,
    StepStatus,
    User,
)
from app.pipeline.events import publish_status
from app.pipeline.tasks import QUEUE_UNAVAILABLE, enqueue_lecture
from app.services.admin import record_action
from app.services.admin_logs import mask_text

RETRY_ONLY_FAILED = "Перезапустить можно только упавшую обработку"
LECTURE_NOT_FOUND = "Лекция не найдена"


async def failed_steps_page(
    session: AsyncSession, only_failed_lectures: bool, limit: int, offset: int
) -> tuple[int, list[tuple[ProcessingStep, Lecture, User | None]]]:
    conditions = [ProcessingStep.status == StepStatus.failed]
    if only_failed_lectures:
        conditions.append(Lecture.status == LectureStatus.failed)
    base = select(ProcessingStep, Lecture, User).join(
        Lecture, Lecture.id == ProcessingStep.lecture_id
    )
    base = base.join(User, User.id == Lecture.owner_id, isouter=True).where(*conditions)
    count = (
        select(func.count())
        .select_from(ProcessingStep)
        .join(Lecture, Lecture.id == ProcessingStep.lecture_id)
        .where(*conditions)
    )
    total = await session.scalar(count) or 0
    rows = await session.execute(
        base.order_by(func.coalesce(ProcessingStep.finished_at, ProcessingStep.created_at).desc())
        .limit(limit)
        .offset(offset)
    )
    return total, [(step, lecture, user) for step, lecture, user in rows]


def masked_error(error: str | None) -> str:
    return mask_text(error or "")


def failed_at(step: ProcessingStep) -> datetime:
    return step.finished_at or step.created_at


async def retry_lecture(session: AsyncSession, actor: User, lecture_id: uuid.UUID) -> Lecture:
    owner = await session.scalar(
        update(Lecture)
        .where(Lecture.id == lecture_id, Lecture.status == LectureStatus.failed)
        .values(status=LectureStatus.queued)
        .returning(Lecture.owner_id)
    )
    if owner is None:
        if await session.get(Lecture, lecture_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, LECTURE_NOT_FOUND)
        raise HTTPException(status.HTTP_409_CONFLICT, RETRY_ONLY_FAILED)
    await session.execute(
        update(ProcessingStep)
        .where(ProcessingStep.lecture_id == lecture_id, ProcessingStep.status == StepStatus.failed)
        .values(status=StepStatus.pending, progress=0.0, stage=None, error=None)
    )
    lecture = await session.get(Lecture, lecture_id, populate_existing=True)
    record_action(
        session,
        actor,
        AdminAction.lecture_retried,
        "lecture",
        str(lecture_id),
        lecture.title if lecture else "",
        {"owner_id": owner},
    )
    await session.commit()
    try:
        await enqueue_lecture(lecture_id)
    except (OSError, RedisError) as error:
        await session.execute(
            update(Lecture).where(Lecture.id == lecture_id).values(status=LectureStatus.failed)
        )
        await session.commit()
        await publish_status(lecture_id, owner, LectureStatus.failed, QUEUE_UNAVAILABLE)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error
    return lecture
