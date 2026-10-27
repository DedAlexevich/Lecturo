import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.notifications import check_quotas, handle_event, send_once


class FakeRedis:
    def __init__(self):
        self.keys = set()

    async def set(self, key, value, nx=False):
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def delete(self, key):
        self.keys.discard(key)


async def test_event_is_owned_and_deduplicated():
    user, lecture = uuid4(), uuid4()
    redis, bot = FakeRedis(), AsyncMock()
    pool = AsyncMock()
    pool.fetchval.return_value = 123
    event = json.dumps({"user_id": str(user), "lecture_id": str(lecture), "status": "ready"})
    await handle_event(event, pool, redis, bot, "https://lecturo.test")
    await handle_event(event, pool, redis, bot, "https://lecturo.test")
    assert bot.send_message.await_count == 1
    args, kwargs = bot.send_message.await_args
    assert args == (123, "Лекция готова.")
    assert kwargs["reply_markup"].inline_keyboard[0][0].web_app.url == (
        f"https://lecturo.test/lectures/{lecture}"
    )
    assert pool.fetchval.await_args.args[1:] == (user, lecture)
    pool.fetchval.return_value = None
    await handle_event(
        event.replace('"ready"', '"failed"'), pool, redis, bot, "https://lecturo.test"
    )
    await handle_event("{}", pool, redis, bot, "https://lecturo.test")
    assert bot.send_message.await_count == 1


async def test_failed_send_can_retry():
    redis, bot = FakeRedis(), AsyncMock()
    bot.send_message.side_effect = [RuntimeError(), None]
    with pytest.raises(RuntimeError):
        await send_once(redis, bot, "test", 1, "message")
    await send_once(redis, bot, "test", 1, "message")
    await send_once(redis, bot, "test", 1, "message")
    assert bot.send_message.await_count == 2


async def test_periodic_notifications_respect_users_cycles_and_packages():
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    first, second = uuid4(), uuid4()
    rows = [
        {
            "id": first,
            "telegram_chat_id": 11,
            "created_at": now - timedelta(days=14),
            "week_start": now - timedelta(minutes=30),
            "subscription_until": now + timedelta(days=3),
            "package_left": 0,
        },
        {
            "id": second,
            "telegram_chat_id": 22,
            "created_at": now - timedelta(days=1),
            "week_start": now - timedelta(days=1),
            "subscription_until": None,
            "package_left": 900,
        },
    ]
    pool, redis, bot = AsyncMock(), FakeRedis(), AsyncMock()
    pool.fetch.return_value = rows
    pool.fetchval.side_effect = lambda query, user, week: 36000 if user == first else 7200
    await check_quotas(pool, redis, bot, 7200, 36000, now)
    await check_quotas(pool, redis, bot, 7200, 36000, now)
    messages = [call.args for call in bot.send_message.await_args_list]
    assert len(messages) == 3
    assert all(message[0] == 11 for message in messages)
    assert {message[1] for message in messages} == {
        "Осталось меньше 15 минут обработки.",
        "Недельный лимит обработки обновлён.",
        "Подписка закончится в течение трёх дней.",
    }
    rows[0]["week_start"] += timedelta(days=7)
    await check_quotas(pool, redis, bot, 7200, 36000, now + timedelta(days=7))
    assert bot.send_message.await_count == 5
