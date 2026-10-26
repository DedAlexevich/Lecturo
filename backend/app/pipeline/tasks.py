import uuid

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Lecture, LectureStatus, SourceType, StepName
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
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, uuid.UUID(lecture_id))
        if lecture is None:
            return "missing"
        lecture.status = LectureStatus.processing
        await session.commit()
        try:
            for name in PLANS[lecture.source_type]:
                await run_step(session, lecture, name, HANDLERS[name])
        except StepFailed:
            return LectureStatus.failed
        lecture.status = LectureStatus.ready
        await session.commit()
        return lecture.status


async def enqueue_lecture(lecture_id: uuid.UUID) -> None:
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        await redis.enqueue_job("process_lecture", str(lecture_id))
    finally:
        await redis.aclose()
