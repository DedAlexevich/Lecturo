from typing import Any

import httpx
from arq import cron
from arq.connections import RedisSettings

from app.core.config import Settings, get_settings
from app.pipeline.retention import delete_expired_videos
from app.pipeline.tasks import process_lecture
from app.providers import get_embeddings, get_llm
from app.providers.openai_compat import OpenAICompatibleEmbeddings

STARTUP_CHECK_TIMEOUT_SECONDS = 15


async def check_providers(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    get_llm(settings)
    if isinstance(get_embeddings(settings), OpenAICompatibleEmbeddings):
        probe = OpenAICompatibleEmbeddings(
            settings, attempts=1, timeout=STARTUP_CHECK_TIMEOUT_SECONDS, transport=transport
        )
        await probe.embed(["проверка"])


async def startup(ctx: dict[str, Any]) -> None:
    await check_providers(get_settings())


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions = [process_lecture]
    on_startup = startup
    job_timeout = 4 * 3600
    keep_result = 0
    cron_jobs = [cron(delete_expired_videos, minute=0)]
