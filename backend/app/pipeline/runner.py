import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lecture, LectureStatus, ProcessingStep, StepName, StepStatus
from app.pipeline.events import publish_status
from app.services.quota import QuotaExceeded

Report = Callable[[float], Awaitable[None]]
StepHandler = Callable[[AsyncSession, Lecture, Report], Awaitable[None]]


class StepFailed(Exception):
    pass


async def get_step(session: AsyncSession, lecture_id: uuid.UUID, name: StepName) -> ProcessingStep:
    step = await session.scalar(
        select(ProcessingStep).where(
            ProcessingStep.lecture_id == lecture_id, ProcessingStep.step == name
        )
    )
    if step is None:
        step = ProcessingStep(lecture_id=lecture_id, step=name, attempts=0, progress=0.0)
        session.add(step)
        await session.flush()
    return step


async def run_step(
    session: AsyncSession, lecture: Lecture, name: StepName, handler: StepHandler
) -> None:
    step = await get_step(session, lecture.id, name)
    if step.status == StepStatus.done:
        return

    step.status = StepStatus.running
    step.progress = 0.0
    step.error = None
    step.attempts += 1
    step.started_at = datetime.now(UTC)
    step.finished_at = None
    await session.commit()

    async def report(progress: float) -> None:
        step.progress = min(max(progress, 0.0), 1.0)
        await session.commit()

    try:
        await handler(session, lecture, report)
    except Exception as error:
        await session.rollback()
        await session.refresh(step)
        await session.refresh(lecture)
        if isinstance(error, QuotaExceeded):
            step.status = StepStatus.pending
            step.error = str(error)
            lecture.status = LectureStatus.waiting_quota
            await session.commit()
            await publish_status(lecture.id, lecture.owner_id, lecture.status, step.error)
            raise
        step.status = StepStatus.failed
        step.error = str(error) or type(error).__name__
        step.finished_at = datetime.now(UTC)
        lecture.status = LectureStatus.failed
        await session.commit()
        await publish_status(lecture.id, lecture.owner_id, lecture.status, step.error)
        raise StepFailed(name) from error

    step.status = StepStatus.done
    step.progress = 1.0
    step.finished_at = datetime.now(UTC)
    await session.commit()
