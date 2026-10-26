import asyncio
import logging

import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.config import load_settings
from app.handlers import build_router

logger = logging.getLogger(__name__)


async def connect(database_url: str) -> asyncpg.Pool | None:
    if not database_url:
        return None
    return await asyncpg.create_pool(database_url, min_size=1, max_size=2)


async def run() -> None:
    settings = load_settings()
    if not settings.token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан, бот не запущен")
        await asyncio.Event().wait()
    pool = await connect(settings.database_url)
    bot = Bot(settings.token)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(settings.public_url, pool))
    try:
        await bot.set_my_commands([BotCommand(command="start", description="Открыть Lecturo")])
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        if pool is not None:
            await pool.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
