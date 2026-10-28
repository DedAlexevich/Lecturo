import logging
import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.constants import abort_jobs_ss
from arq.jobs import Job, JobStatus
from arq.utils import timestamp_ms
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = (JobStatus.deferred, JobStatus.queued, JobStatus.in_progress)


def lecture_job_id(lecture_id: uuid.UUID) -> str:
    return f"lecture:{lecture_id}"


def regeneration_job_id(lecture_id: uuid.UUID) -> str:
    return f"regenerate:{lecture_id}"


def quiz_job_id(lecture_id: uuid.UUID) -> str:
    return f"quiz:{lecture_id}"


def video_job_id(lecture_id: uuid.UUID) -> str:
    return f"video:{lecture_id}"


def lecture_job_ids(lecture_id: uuid.UUID) -> list[str]:
    return [
        lecture_job_id(lecture_id),
        video_job_id(lecture_id),
        quiz_job_id(lecture_id),
        regeneration_job_id(lecture_id),
    ]


def queue_settings() -> RedisSettings:
    settings = RedisSettings.from_dsn(get_settings().redis_url)
    settings.conn_retries = 0
    return settings


async def abort_on(redis: ArqRedis, job_id: str) -> bool:
    job = Job(job_id, redis)
    if await job.status() not in ACTIVE_JOB_STATUSES:
        return False
    await redis.zadd(abort_jobs_ss, {job.job_id: timestamp_ms()})
    return True


async def abort_job(job_id: str) -> bool:
    redis = await create_pool(queue_settings())
    try:
        return await abort_on(redis, job_id)
    finally:
        await redis.aclose()


async def cancel_lecture_jobs(lecture_ids: list[uuid.UUID]) -> None:
    if not lecture_ids:
        return
    try:
        redis = await create_pool(queue_settings())
        try:
            for lecture_id in lecture_ids:
                for job_id in lecture_job_ids(lecture_id):
                    await abort_on(redis, job_id)
        finally:
            await redis.aclose()
    except (OSError, RedisError):
        logger.warning("Не удалось отменить задачи лекций: очередь недоступна", exc_info=True)
