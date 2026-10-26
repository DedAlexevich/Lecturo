from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import Settings, get_settings
from app.models import EMBEDDING_DIM
from app.pipeline.retention import delete_expired_videos
from app.pipeline.tasks import process_lecture
from app.providers import get_embeddings, get_llm


async def check_providers(settings: Settings) -> None:
    get_llm(settings)
    embeddings = get_embeddings(settings)
    if settings.embeddings_provider == "stub":
        return
    [vector] = await embeddings.embed(["проверка"])
    if len(vector) != EMBEDDING_DIM:
        raise RuntimeError(
            f"Модель эмбеддингов {settings.embeddings_model} отдаёт векторы размерности "
            f"{len(vector)}, а EMBEDDING_DIM = {EMBEDDING_DIM}"
        )


async def startup(ctx: dict[str, Any]) -> None:
    await check_providers(get_settings())


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions = [process_lecture]
    on_startup = startup
    job_timeout = 4 * 3600
    keep_result = 0
    cron_jobs = [cron(delete_expired_videos, minute=0)]
