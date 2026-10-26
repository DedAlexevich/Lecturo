import uuid

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Lecture, LectureStatus, ProcessingStep, SourceType, StepName, StepStatus
from app.pipeline import stages
from app.pipeline.runner import StepFailed, StepHandler, run_step

HANDLERS: dict[StepName, StepHandler] = {
    StepName.transcribe: stages.transcribe,
    StepName.summarize: stages.summarize,
    StepName.embed: stages.embed,
}

PLANS: dict[SourceType, list[StepName]] = {
    SourceType.upload: [StepName.transcribe, StepName.summarize, StepName.embed],
    SourceType.link: [StepName.transcribe, StepName.summarize, StepName.embed],
    SourceType.local: [StepName.embed],
}


async def process_lecture(ctx: dict, lecture_id: str) -> str:
    lecture_uuid = uuid.UUID(lecture_id)
    try:
        return await run_plan(lecture_uuid)
    except StepFailed:
        return LectureStatus.failed
    except BaseException as error:
        await mark_failed(lecture_uuid, str(error) or type(error).__name__)
        raise


async def run_plan(lecture_id: uuid.UUID) -> str:
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, lecture_id)
        if lecture is None:
            return "missing"
        lecture.status = LectureStatus.processing
        await session.commit()
        for name in PLANS[lecture.source_type]:
            await run_step(session, lecture, name, HANDLERS[name])
        lecture.status = LectureStatus.ready
        await session.commit()
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
        await session.execute(
            update(Lecture).where(Lecture.id == lecture_id).values(status=LectureStatus.failed)
        )
        await session.commit()


async def enqueue_lecture(lecture_id: uuid.UUID) -> None:
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        await redis.enqueue_job("process_lecture", str(lecture_id))
    finally:
        await redis.aclose()
