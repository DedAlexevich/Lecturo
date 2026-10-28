import asyncio
import logging
from collections.abc import Awaitable

import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from redis.asyncio import Redis

from app.alerts import admin_alerts_loop, build_alerts_router
from app.config import load_settings
from app.handlers import build_router
from app.heartbeat import heartbeat_loop
from app.logs import configure_logging
from app.notifications import lecture_notices_loop, legal_notices_loop, quota_loop

logger = logging.getLogger(__name__)


async def connect(database_url: str) -> asyncpg.Pool | None:
    if not database_url:
        return None
    return await asyncpg.create_pool(database_url, min_size=1, max_size=2)


async def serve(polling: Awaitable, tasks: list[asyncio.Task]) -> None:
    polling_task = asyncio.ensure_future(polling)
    done, _ = await asyncio.wait([polling_task, *tasks], return_when=asyncio.FIRST_COMPLETED)
    if polling_task in done:
        polling_task.result()
        return
    polling_task.cancel()
    await asyncio.gather(polling_task, return_exceptions=True)
    for task in done:
        error = None if task.cancelled() else task.exception()
        logger.error("Фоновая задача %s остановилась", task.get_name(), exc_info=error)
    raise SystemExit(1)


async def run() -> None:
    settings = load_settings()
    heartbeat = asyncio.create_task(heartbeat_loop(), name="heartbeat")
    if not settings.token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан, бот не запущен")
        await asyncio.Event().wait()
    pool = await connect(settings.database_url)
    bot = Bot(settings.token)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_alerts_router(pool, settings.admin_alert_interval))
    dispatcher.include_router(build_router(settings.public_url, pool))
    redis = Redis.from_url(settings.bot_redis_url)
    tasks = [heartbeat]
    if pool is not None:
        tasks += [
            asyncio.create_task(
                lecture_notices_loop(pool, bot, settings.public_url), name="lecture-notices"
            ),
            asyncio.create_task(
                quota_loop(
                    pool,
                    redis,
                    bot,
                    settings.free_weekly_seconds,
                    settings.subscription_weekly_seconds,
                ),
                name="quotas",
            ),
            asyncio.create_task(legal_notices_loop(pool, redis, bot), name="legal-notices"),
            asyncio.create_task(
                admin_alerts_loop(pool, bot, settings.admin_alert_interval), name="admin-alerts"
            ),
        ]
    try:
        await bot.set_my_commands([BotCommand(command="start", description="Открыть Lecturo")])
        await serve(dispatcher.start_polling(bot), tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await redis.aclose()
        await bot.session.close()
        if pool is not None:
            await pool.close()


def main() -> None:
    configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
