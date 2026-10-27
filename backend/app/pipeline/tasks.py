import asyncio
import uuid

from arq import create_pool
from arq.connections import RedisSettings
from arq.constants import abort_jobs_ss
from arq.jobs import Job, JobStatus
from arq.utils import timestamp_ms
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Lecture, LectureStatus, ProcessingStep, SourceType, StepName, StepStatus
from app.pipeline import download, embed, media, quiz, stages, summarize
from app.pipeline.events import publish_status
from app.pipeline.runner import StepFailed, StepHandler, get_step, run_step
from app.services import quota
from app.services.account import lecture_files, remove_files

HANDLERS: dict[StepName, StepHandler] = {
    StepName.download: download.download,
    StepName.audio: media.extract_audio,
    StepName.video: media.transcode_video,
    StepName.transcribe: stages.transcribe,
    StepName.summarize: summarize.summarize,
    StepName.embed: embed.embed,
}

REGENERATION_STEPS = [StepName.summarize, StepName.embed]

ACTIVE_JOB_STATUSES = (JobStatus.deferred, JobStatus.queued, JobStatus.in_progress)

PLANS: dict[SourceType, list[StepName]] = {
    SourceType.upload: [
        StepName.audio,
        StepName.video,
        StepName.transcribe,
        StepName.summarize,
        StepName.embed,
    ],
    SourceType.link: [StepName.download, StepName.transcribe, StepName.summarize, StepName.embed],
    SourceType.local: [StepName.embed],
}


async def process_lecture(ctx: dict, lecture_id: str) -> str:
    lecture_uuid = uuid.UUID(lecture_id)
    try:
        return await run_plan(lecture_uuid)
    except quota.QuotaExceeded:
        return LectureStatus.waiting_quota
    except StepFailed:
        await refund(lecture_uuid)
        return LectureStatus.failed
    except BaseException as error:
        await mark_failed(lecture_uuid, str(error) or type(error).__name__)
        raise
    finally:
        await purge_if_deleted(lecture_uuid)


async def process_regeneration(ctx: dict, lecture_id: str) -> str:
    lecture_uuid = uuid.UUID(lecture_id)
    try:
        return await run_regeneration(lecture_uuid)
    except BaseException as error:
        await restore_ready(lecture_uuid, str(error) or type(error).__name__)
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
        except StepFailed:
            outcome = StepStatus.failed
            failed = await get_step(session, lecture.id, StepName.summarize)
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
        await session.commit()
        await publish_status(lecture.id, lecture.owner_id, lecture.status, error)
        return outcome


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
        await session.commit()
    if owner_id is not None:
        await publish_status(lecture_id, owner_id, LectureStatus.ready, error)


async def process_quiz(ctx: dict, lecture_id: str) -> str:
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, uuid.UUID(lecture_id))
        if lecture is None:
            return "missing"
        try:
            await run_step(session, lecture, StepName.quiz, quiz.build_quiz, fails_lecture=False)
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
        lecture.status = LectureStatus.processing
        await session.commit()
        await publish_status(lecture.id, lecture.owner_id, lecture.status)
        for name in PLANS[lecture.source_type]:
            await run_step(session, lecture, name, HANDLERS[name])
        lecture.status = LectureStatus.ready
        await session.commit()
        await publish_status(lecture.id, lecture.owner_id, lecture.status)
        return lecture.status


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
        await session.commit()
    if owner_id is not None:
        await publish_status(lecture_id, owner_id, LectureStatus.failed, error)


async def refund(lecture_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        await quota.refund_failed_lecture(session, lecture_id)
        await session.commit()


def lecture_job_id(lecture_id: uuid.UUID) -> str:
    return f"lecture:{lecture_id}"


async def enqueue_lecture(lecture_id: uuid.UUID) -> None:
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        await redis.enqueue_job(
            "process_lecture", str(lecture_id), _job_id=lecture_job_id(lecture_id)
        )
    finally:
        await redis.aclose()


def regeneration_job_id(lecture_id: uuid.UUID) -> str:
    return f"regenerate:{lecture_id}"


async def enqueue_regeneration(lecture_id: uuid.UUID) -> None:
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        await redis.enqueue_job(
            "process_regeneration", str(lecture_id), _job_id=regeneration_job_id(lecture_id)
        )
    finally:
        await redis.aclose()


def quiz_job_id(lecture_id: uuid.UUID) -> str:
    return f"quiz:{lecture_id}"


async def enqueue_quiz(lecture_id: uuid.UUID) -> None:
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        await redis.enqueue_job("process_quiz", str(lecture_id), _job_id=quiz_job_id(lecture_id))
    finally:
        await redis.aclose()


async def quiz_job_active(lecture_id: uuid.UUID) -> bool:
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        return await Job(quiz_job_id(lecture_id), redis).status() in ACTIVE_JOB_STATUSES
    finally:
        await redis.aclose()


async def cancel_lecture_job(lecture_id: uuid.UUID) -> bool:
    return await abort_job(lecture_job_id(lecture_id))


async def cancel_quiz_job(lecture_id: uuid.UUID) -> bool:
    return await abort_job(quiz_job_id(lecture_id))


async def cancel_regeneration_job(lecture_id: uuid.UUID) -> bool:
    return await abort_job(regeneration_job_id(lecture_id))


async def abort_job(job_id: str) -> bool:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    redis_settings.conn_retries = 0
    redis = await create_pool(redis_settings)
    try:
        job = Job(job_id, redis)
        if await job.status() not in ACTIVE_JOB_STATUSES:
            return False
        await redis.zadd(abort_jobs_ss, {job.job_id: timestamp_ms()})
        return True
    finally:
        await redis.aclose()
