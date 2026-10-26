from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.pipeline.retention import delete_expired_videos
from app.pipeline.tasks import process_lecture


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions = [process_lecture]
    cron_jobs = [cron(delete_expired_videos, minute=0)]
