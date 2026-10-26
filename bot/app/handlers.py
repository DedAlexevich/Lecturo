import logging

import asyncpg
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from app.storage import save_chat_id

logger = logging.getLogger(__name__)

GREETING = (
    "Привет! Lecturo превращает записи лекций в конспекты, карточки и тесты. "
    "Откройте приложение, чтобы загрузить лекцию, а я напишу, когда всё будет готово."
)


def open_app_markup(public_url: str) -> InlineKeyboardMarkup | None:
    if not public_url.startswith("https://"):
        return None
    button = InlineKeyboardButton(text="Открыть Lecturo", web_app=WebAppInfo(url=public_url))
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def build_router(public_url: str, pool: asyncpg.Pool | None) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if pool is not None and message.from_user is not None:
            try:
                await save_chat_id(pool, message.from_user.id, message.chat.id)
            except (asyncpg.PostgresError, OSError):
                logger.exception("не удалось сохранить chat_id")
        await message.answer(GREETING, reply_markup=open_app_markup(public_url))

    return router
