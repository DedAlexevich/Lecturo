import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    Lecture,
    LectureStatus,
    NotificationKind,
    NotificationOutcome,
    ProcessingStep,
    StepName,
    StepStatus,
)
from app.pipeline.events import add_notification, publish_status
from app.providers.openai_compat import OpenAICompatibleUnavailable
from app.services.quota import QuotaExceeded

logger = logging.getLogger(__name__)


class Report(Protocol):
    async def __call__(self, progress: float, stage: str | None = None) -> None: ...


StepHandler = Callable[[AsyncSession, Lecture, Report], Awaitable[None]]


class StepFailed(Exception):
    pass


class StepDeferred(Exception):
    def __init__(self, name: StepName, delay: int) -> None:
        super().__init__(name)
        self.delay = delay


class UserFacingError(Exception):
    pass


TRANSIENT_ERRORS = (OpenAICompatibleUnavailable,)


def deferral_delay(ctx: dict) -> int | None:
    delays = get_settings().llm_retry_defer_seconds
    job_try = ctx.get("job_try", 1)
    if job_try > len(delays):
        return None
    return delays[job_try - 1]


PROCESSING_FAILED = "Не удалось обработать лекцию, попробуйте ещё раз"

STEP_ERRORS = {
    StepName.download: "Не удалось скачать запись по ссылке, попробуйте позже",
    StepName.audio: "Не удалось извлечь звук из записи",
    StepName.video: "Не удалось пережать видео",
    StepName.transcribe: "Сервис распознавания недоступен, попробуйте позже",
    StepName.summarize: "Сервис конспектов недоступен, попробуйте позже",
    StepName.embed: "Не удалось подготовить поиск по лекции, попробуйте позже",
    StepName.quiz: "Не удалось собрать квиз, попробуйте позже",
}


def step_error(name: StepName, error: Exception) -> str:
    if isinstance(error, UserFacingError):
        return str(error)
    return STEP_ERRORS.get(name, PROCESSING_FAILED)


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
    session: AsyncSession,
    lecture: Lecture,
    name: StepName,
    handler: StepHandler,
    *,
    fails_lecture: bool = True,
    notify: NotificationKind | None = None,
    defer_delay: int | None = None,
) -> None:
    step = await get_step(session, lecture.id, name)
    if step.status == StepStatus.done:
        return

    step.status = StepStatus.running
    step.progress = 0.0
    step.stage = None
    step.error = None
    step.attempts += 1
    step.started_at = datetime.now(UTC)
    step.finished_at = None
    await session.commit()

    async def report(progress: float, stage: str | None = None) -> None:
        step.progress = min(max(progress, 0.0), 1.0)
        step.stage = stage
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
            step.progress = 0.0
            step.stage = None
            step.attempts -= 1
            step.started_at = None
            lecture.status = LectureStatus.waiting_quota
            await session.commit()
            await publish_status(lecture.id, lecture.owner_id, lecture.status, step.error)
            raise
        if defer_delay is not None and isinstance(error, TRANSIENT_ERRORS):
            logger.warning(
                "Шаг %s лекции %s отложен на %s с из-за временной ошибки провайдера: %s",
                name.value,
                lecture.id,
                defer_delay,
                error,
            )
            step.status = StepStatus.pending
            step.progress = 0.0
            step.stage = None
            step.started_at = None
            await session.commit()
            raise StepDeferred(name, defer_delay) from error
        logger.error("Шаг %s лекции %s завершился ошибкой", name.value, lecture.id, exc_info=error)
        step.status = StepStatus.failed
        step.error = step_error(name, error)
        step.finished_at = datetime.now(UTC)
        if fails_lecture:
            lecture.status = LectureStatus.failed
            notify = NotificationKind.lecture
        if notify is not None:
            add_notification(
                session, lecture.id, lecture.owner_id, notify, NotificationOutcome.failed
            )
        await session.commit()
        if fails_lecture:
            await publish_status(lecture.id, lecture.owner_id, lecture.status, step.error)
        raise StepFailed(name) from error

    step.status = StepStatus.done
    step.progress = 1.0
    step.stage = None
    step.finished_at = datetime.now(UTC)
    if notify is not None:
        add_notification(session, lecture.id, lecture.owner_id, notify, NotificationOutcome.ready)
    await session.commit()
