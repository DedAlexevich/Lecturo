import logging
from typing import Any

import httpx
from arq import cron, func
from arq.connections import RedisSettings

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.redis import close_redis
from app.pipeline.exam import build_exam_sheet
from app.pipeline.retention import delete_expired_videos, delete_stale_uploads
from app.pipeline.tasks import (
    LECTURE_TIMEOUT_SEC,
    VIDEO_TIMEOUT_SEC,
    process_lecture,
    process_quiz,
    process_regeneration,
    process_video,
    resume_interrupted_lectures,
)
from app.pipeline.zoomer import ZOOMER_TIMEOUT_SEC, process_zoomer_video
from app.providers import get_embeddings, get_llm
from app.providers.openai_compat import OpenAICompatibleEmbeddings, OpenAICompatibleUnavailable
from app.providers.yandex import YandexEmbeddings
from app.services.legal_notices import process_legal_revisions
from app.services.quota import delete_expired_carryovers

logger = logging.getLogger(__name__)

STARTUP_CHECK_TIMEOUT_SECONDS = 15


async def check_providers(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    get_llm(settings)
    embeddings = get_embeddings(settings)
    if isinstance(embeddings, OpenAICompatibleEmbeddings | YandexEmbeddings):
        probe = type(embeddings)(
            settings, attempts=1, timeout=STARTUP_CHECK_TIMEOUT_SECONDS, transport=transport
        )
        try:
            await probe.embed_query("проверка")
        except OpenAICompatibleUnavailable as error:
            logger.error("API эмбеддингов недоступно, поиск по лекциям не заработает: %s", error)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    await check_providers(get_settings())
    await resume_interrupted_lectures(ctx["redis"])


async def shutdown(ctx: dict[str, Any]) -> None:
    await close_redis()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions = [
        process_lecture,
        func(process_video, timeout=VIDEO_TIMEOUT_SEC + 600),
        process_quiz,
        process_regeneration,
        build_exam_sheet,
        func(process_zoomer_video, timeout=ZOOMER_TIMEOUT_SEC, max_tries=3),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = get_settings().worker_max_jobs
    job_timeout = LECTURE_TIMEOUT_SEC + 600
    max_tries = 100
    keep_result = 0
    allow_abort_jobs = True
    health_check_interval = 30
    cron_jobs = [
        cron(delete_expired_videos, minute=0),
        cron(delete_stale_uploads, minute=30),
        cron(delete_expired_carryovers, minute=15),
        cron(process_legal_revisions, minute=set(range(0, 60, 10))),
    ]
