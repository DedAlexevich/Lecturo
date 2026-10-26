import asyncio
import uuid

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Lecture, LectureStatus, ProcessingStep, SourceType, StepName, StepStatus
from app.pipeline import download, media, stages, summarize
from app.pipeline.events import publish_status
from app.pipeline.runner import StepFailed, StepHandler, run_step
from app.services import quota
from app.services.account import lecture_files, remove_files

HANDLERS: dict[StepName, StepHandler] = {
    StepName.download: download.download,
    StepName.audio: media.extract_audio,
    StepName.video: media.transcode_video,
    StepName.transcribe: stages.transcribe,
    StepName.summarize: summarize.summarize,
    StepName.embed: stages.embed,
}

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


async def enqueue_lecture(lecture_id: uuid.UUID) -> None:
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        await redis.enqueue_job("process_lecture", str(lecture_id), _job_id=f"lecture:{lecture_id}")
    finally:
        await redis.aclose()
