from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.pipeline.retention import delete_expired_videos


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions: list = []
    cron_jobs = [cron(delete_expired_videos, minute=0)]
