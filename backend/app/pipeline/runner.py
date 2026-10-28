import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
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


DEFERRALS_TTL_SECONDS = 24 * 3600


def deferrals_key(scope: str) -> str:
    return f"llm-deferrals:{scope}"


async def next_deferral(scope: str) -> int | None:
    settings = get_settings()
    redis = get_redis(settings.redis_url)
    key = deferrals_key(scope)
    delays = settings.llm_retry_defer_seconds
    try:
        used = await redis.incr(key)
        await redis.expire(key, DEFERRALS_TTL_SECONDS)
        if used > len(delays):
            await redis.delete(key)
            return None
    except (OSError, RedisError):
        logger.warning("Не удалось посчитать отложенные повторы %s", scope, exc_info=True)
        return None
    return delays[used - 1]


async def reset_deferrals(scope: str) -> None:
    try:
        await get_redis(get_settings().redis_url).delete(deferrals_key(scope))
    except (OSError, RedisError):
        logger.warning("Не удалось сбросить счётчик повторов %s", scope, exc_info=True)


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
    defer_scope: str | None = None,
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
        delay = None
        if defer_scope is not None and isinstance(error, TRANSIENT_ERRORS):
            delay = await next_deferral(defer_scope)
        if delay is not None:
            logger.warning(
                "Шаг %s лекции %s отложен на %s с из-за временной ошибки провайдера: %s",
                name.value,
                lecture.id,
                delay,
                error,
            )
            step.status = StepStatus.pending
            step.progress = 0.0
            step.stage = None
            step.started_at = None
            await session.commit()
            raise StepDeferred(name, delay) from error
        if defer_scope is not None:
            await reset_deferrals(defer_scope)
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

    if defer_scope is not None:
        await reset_deferrals(defer_scope)
    step.status = StepStatus.done
    step.progress = 1.0
    step.stage = None
    step.finished_at = datetime.now(UTC)
    if notify is not None:
        add_notification(session, lecture.id, lecture.owner_id, notify, NotificationOutcome.ready)
    await session.commit()
