import asyncio
import logging
import uuid

from arq import Retry, create_pool
from arq.connections import ArqRedis
from arq.constants import default_queue_name, in_progress_key_prefix
from arq.jobs import Job
from redis.exceptions import RedisError
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import (
    Lecture,
    LectureStatus,
    NotificationKind,
    NotificationOutcome,
    ProcessingStep,
    SourceType,
    StepName,
    StepStatus,
)
from app.pipeline import download, embed, media, quiz, stages, summarize
from app.pipeline.estimate import LECTURE_TIMEOUT_SEC
from app.pipeline.events import add_notification, publish_status
from app.pipeline.jobs import (
    ACTIVE_JOB_STATUSES,
    lecture_job_id,
    queue_settings,
    quiz_job_id,
    regeneration_job_id,
    video_job_id,
)
from app.pipeline.runner import PROCESSING_FAILED, StepFailed, StepHandler, get_step, run_step
from app.services import quota
from app.services.account import lecture_files, remove_files

logger = logging.getLogger(__name__)

REGENERATION_TIMEOUT_SEC = LECTURE_TIMEOUT_SEC
VIDEO_TIMEOUT_SEC = 2 * 3600
VIDEO_ATTEMPTS = 5
VIDEO_RETRY_DELAY_SEC = 300
VIDEO_TIMED_OUT = "Пережатие видео заняло слишком много времени"

HANDLERS: dict[StepName, StepHandler] = {
    StepName.download: download.download,
    StepName.audio: media.extract_audio,
    StepName.video: media.transcode_video,
    StepName.transcribe: stages.transcribe,
    StepName.summarize: summarize.summarize,
    StepName.embed: embed.embed,
}

REGENERATION_STEPS = [StepName.summarize, StepName.embed]
REGENERATION_FAILED = "Не удалось пересоздать главы и конспект, попробуйте позже"
QUEUE_UNAVAILABLE = "Очередь недоступна, попробуйте позже"

PLANS: dict[SourceType, list[StepName]] = {
    SourceType.upload: [StepName.audio, StepName.transcribe, StepName.summarize, StepName.embed],
    SourceType.link: [StepName.download, StepName.transcribe, StepName.summarize, StepName.embed],
    SourceType.local: [StepName.embed],
}

AFTER_READY: dict[SourceType, list[StepName]] = {SourceType.upload: [StepName.video]}

AFTER_READY_STEPS = sorted({name for names in AFTER_READY.values() for name in names})

LECTURE_STEPS = [name for name in StepName if name != StepName.quiz]


async def process_lecture(ctx: dict, lecture_id: str) -> str:
    lecture_uuid = uuid.UUID(lecture_id)
    try:
        async with asyncio.timeout(LECTURE_TIMEOUT_SEC):
            return await run_plan(lecture_uuid)
    except quota.QuotaExceeded:
        return LectureStatus.waiting_quota
    except StepFailed:
        await refund(lecture_uuid)
        return LectureStatus.failed
    except asyncio.CancelledError:
        await return_to_queue([lecture_uuid])
        raise
    except BaseException:
        await mark_failed(lecture_uuid, PROCESSING_FAILED)
        raise
    finally:
        await purge_if_deleted(lecture_uuid)


async def process_video(ctx: dict, lecture_id: str) -> str:
    lecture_uuid = uuid.UUID(lecture_id)
    try:
        async with asyncio.timeout(VIDEO_TIMEOUT_SEC):
            return await run_after_ready(lecture_uuid)
    except StepFailed as failure:
        if isinstance(failure.__cause__, OSError) and ctx.get("job_try", 1) < VIDEO_ATTEMPTS:
            await return_after_ready_to_queue(lecture_uuid)
            raise Retry(defer=VIDEO_RETRY_DELAY_SEC) from failure
        await asyncio.to_thread(media.original_path(lecture_uuid).unlink, missing_ok=True)
        return StepStatus.failed
    except TimeoutError:
        await fail_after_ready(lecture_uuid, VIDEO_TIMED_OUT)
        await asyncio.to_thread(media.original_path(lecture_uuid).unlink, missing_ok=True)
        return StepStatus.failed
    except asyncio.CancelledError:
        await return_to_queue([lecture_uuid])
        raise
    finally:
        await purge_if_deleted(lecture_uuid)


async def run_after_ready(lecture_id: uuid.UUID) -> str:
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, lecture_id)
        if lecture is None:
            return "missing"
        for name in AFTER_READY.get(lecture.source_type, []):
            await run_step(session, lecture, name, HANDLERS[name], fails_lecture=False)
        return StepStatus.done


async def return_after_ready_to_queue(lecture_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(ProcessingStep)
            .where(
                ProcessingStep.lecture_id == lecture_id,
                ProcessingStep.step.in_(AFTER_READY_STEPS),
                ProcessingStep.status == StepStatus.failed,
            )
            .values(status=StepStatus.pending, progress=0.0, stage=None, error=None)
        )
        await session.commit()


async def fail_after_ready(lecture_id: uuid.UUID, error: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(ProcessingStep)
            .where(
                ProcessingStep.lecture_id == lecture_id,
                ProcessingStep.step.in_(AFTER_READY_STEPS),
                ProcessingStep.status == StepStatus.running,
            )
            .values(status=StepStatus.failed, error=error)
        )
        await session.commit()


async def schedule_after_ready(session: AsyncSession, lecture: Lecture) -> None:
    for name in AFTER_READY.get(lecture.source_type, []):
        if (await get_step(session, lecture.id, name)).status != StepStatus.done:
            await session.commit()
            try:
                await enqueue_video(lecture.id)
            except (OSError, RedisError):
                logger.warning("Не удалось поставить пережатие видео лекции %s", lecture.id)
            return


async def process_regeneration(ctx: dict, lecture_id: str) -> str:
    lecture_uuid = uuid.UUID(lecture_id)
    try:
        async with asyncio.timeout(REGENERATION_TIMEOUT_SEC):
            await reset_regeneration_steps(lecture_uuid)
            return await run_regeneration(lecture_uuid)
    except asyncio.CancelledError:
        raise
    except BaseException:
        await restore_ready(lecture_uuid, REGENERATION_FAILED)
        raise


async def run_regeneration(lecture_id: uuid.UUID) -> str:
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, lecture_id)
        if lecture is None:
            return "missing"
        outcome = StepStatus.done
        error: str | None = None
        try:
            for name in REGENERATION_STEPS:
                await run_step(session, lecture, name, HANDLERS[name], fails_lecture=False)
        except StepFailed as failure:
            outcome = StepStatus.failed
            failed = await get_step(session, lecture.id, failure.args[0])
            error = failed.error
            await session.execute(
                update(ProcessingStep)
                .where(
                    ProcessingStep.lecture_id == lecture_id,
                    ProcessingStep.step.in_(REGENERATION_STEPS),
                    ProcessingStep.status == StepStatus.pending,
                )
                .values(status=StepStatus.done, progress=1.0)
            )
        lecture.status = LectureStatus.ready
        add_notification(
            session,
            lecture.id,
            lecture.owner_id,
            NotificationKind.regenerate,
            NotificationOutcome.ready if outcome == StepStatus.done else NotificationOutcome.failed,
        )
        await session.commit()
        await publish_status(lecture.id, lecture.owner_id, lecture.status, error)
        return outcome


async def reset_regeneration_steps(lecture_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(ProcessingStep)
            .where(
                ProcessingStep.lecture_id == lecture_id,
                ProcessingStep.step.in_(REGENERATION_STEPS),
            )
            .values(status=StepStatus.pending, progress=0.0, stage=None, error=None)
        )
        await session.commit()


async def restore_ready(lecture_id: uuid.UUID, error: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(ProcessingStep)
            .where(
                ProcessingStep.lecture_id == lecture_id,
                ProcessingStep.step.in_(REGENERATION_STEPS),
                ProcessingStep.status == StepStatus.running,
            )
            .values(status=StepStatus.failed, error=error)
        )
        await session.execute(
            update(ProcessingStep)
            .where(
                ProcessingStep.lecture_id == lecture_id,
                ProcessingStep.step.in_(REGENERATION_STEPS),
                ProcessingStep.status == StepStatus.pending,
            )
            .values(status=StepStatus.done, progress=1.0)
        )
        owner_id = await session.scalar(
            update(Lecture)
            .where(Lecture.id == lecture_id, Lecture.status == LectureStatus.processing)
            .values(status=LectureStatus.ready)
            .returning(Lecture.owner_id)
        )
        if owner_id is not None:
            add_notification(
                session,
                lecture_id,
                owner_id,
                NotificationKind.regenerate,
                NotificationOutcome.failed,
            )
        await session.commit()
    if owner_id is not None:
        await publish_status(lecture_id, owner_id, LectureStatus.ready, error)


async def process_quiz(ctx: dict, lecture_id: str) -> str:
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, uuid.UUID(lecture_id))
        if lecture is None:
            return "missing"
        try:
            await run_step(
                session,
                lecture,
                StepName.quiz,
                quiz.build_quiz,
                fails_lecture=False,
                notify=NotificationKind.quiz,
            )
        except StepFailed:
            return StepStatus.failed
        return StepStatus.done


async def purge_if_deleted(lecture_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        exists = await session.scalar(select(Lecture.id).where(Lecture.id == lecture_id))
    if exists is None:
        await asyncio.to_thread(remove_files, lecture_files(lecture_id, []))


async def run_plan(lecture_id: uuid.UUID) -> str:
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, lecture_id)
        if lecture is None:
            return "missing"
        if lecture.status != LectureStatus.ready:
            lecture.status = LectureStatus.processing
            await session.commit()
            await publish_status(lecture.id, lecture.owner_id, lecture.status)
            for name in PLANS[lecture.source_type]:
                await run_step(session, lecture, name, HANDLERS[name])
            for name in AFTER_READY.get(lecture.source_type, []):
                await get_step(session, lecture.id, name)
            lecture.status = LectureStatus.ready
            add_notification(
                session,
                lecture.id,
                lecture.owner_id,
                NotificationKind.lecture,
                NotificationOutcome.ready,
            )
            await session.commit()
            await publish_status(lecture.id, lecture.owner_id, lecture.status)
        await schedule_after_ready(session, lecture)
        return lecture.status


async def return_to_queue(lecture_ids: list[uuid.UUID]) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(ProcessingStep)
            .where(
                ProcessingStep.lecture_id.in_(lecture_ids),
                ProcessingStep.step.in_(LECTURE_STEPS),
                ProcessingStep.status == StepStatus.running,
            )
            .values(status=StepStatus.pending, progress=0.0, stage=None)
        )
        await session.execute(
            update(Lecture)
            .where(Lecture.id.in_(lecture_ids), Lecture.status == LectureStatus.processing)
            .values(status=LectureStatus.queued)
        )
        await session.commit()


async def release_orphaned_jobs(redis: ArqRedis) -> None:
    job_ids = await redis.zrange(default_queue_name, 0, -1)
    if job_ids:
        await redis.delete(*(in_progress_key_prefix + job_id.decode() for job_id in job_ids))


async def resume_interrupted_lectures(redis: ArqRedis) -> int:
    await release_orphaned_jobs(redis)
    async with SessionLocal() as session:
        running = select(ProcessingStep.lecture_id).where(
            ProcessingStep.step.in_(LECTURE_STEPS), ProcessingStep.status == StepStatus.running
        )
        after_ready = select(ProcessingStep.lecture_id).where(
            ProcessingStep.step.in_(AFTER_READY_STEPS), ProcessingStep.status == StepStatus.pending
        )
        candidates = await session.scalars(
            select(Lecture.id).where(
                or_(
                    Lecture.status.in_([LectureStatus.queued, LectureStatus.processing]),
                    Lecture.id.in_(running),
                    (Lecture.status == LectureStatus.ready) & Lecture.id.in_(after_ready),
                )
            )
        )
    lecture_ids = [
        lecture_id
        for lecture_id in candidates
        if await Job(regeneration_job_id(lecture_id), redis).info() is None
    ]
    if not lecture_ids:
        return 0
    await return_to_queue(lecture_ids)
    resumed = 0
    for lecture_id in lecture_ids:
        job_id = lecture_job_id(lecture_id)
        if await Job(job_id, redis).info() is None:
            await redis.enqueue_job("process_lecture", str(lecture_id), _job_id=job_id)
            resumed += 1
    logger.info(
        "После перезапуска не закончено лекций: %s, заново поставлено в очередь: %s",
        len(lecture_ids),
        resumed,
    )
    return resumed


async def mark_failed(lecture_id: uuid.UUID, error: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(ProcessingStep)
            .where(
                ProcessingStep.lecture_id == lecture_id,
                ProcessingStep.status == StepStatus.running,
            )
            .values(status=StepStatus.failed, error=error)
        )
        owner_id = await session.scalar(
            update(Lecture)
            .where(Lecture.id == lecture_id, Lecture.status != LectureStatus.ready)
            .values(status=LectureStatus.failed)
            .returning(Lecture.owner_id)
        )
        if owner_id is not None:
            await quota.refund_failed_lecture(session, lecture_id)
            add_notification(
                session, lecture_id, owner_id, NotificationKind.lecture, NotificationOutcome.failed
            )
        await session.commit()
    if owner_id is not None:
        await publish_status(lecture_id, owner_id, LectureStatus.failed, error)


async def refund(lecture_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        await quota.refund_failed_lecture(session, lecture_id)
        await session.commit()


async def enqueue(name: str, job_id: str, *args: str) -> None:
    redis = await create_pool(queue_settings())
    try:
        await redis.enqueue_job(name, *args, _job_id=job_id)
    finally:
        await redis.aclose()


async def enqueue_lecture(lecture_id: uuid.UUID) -> None:
    await enqueue("process_lecture", lecture_job_id(lecture_id), str(lecture_id))


async def enqueue_video(lecture_id: uuid.UUID) -> None:
    await enqueue("process_video", video_job_id(lecture_id), str(lecture_id))


async def enqueue_regeneration(lecture_id: uuid.UUID) -> None:
    await enqueue("process_regeneration", regeneration_job_id(lecture_id), str(lecture_id))


async def enqueue_quiz(lecture_id: uuid.UUID) -> None:
    await enqueue("process_quiz", quiz_job_id(lecture_id), str(lecture_id))


async def quiz_job_active(lecture_id: uuid.UUID) -> bool:
    redis = await create_pool(queue_settings())
    try:
        return await Job(quiz_job_id(lecture_id), redis).status() in ACTIVE_JOB_STATUSES
    finally:
        await redis.aclose()
