from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.methods import SendMessage

from app.notifications import (
    CLOSE_LECTURE_NOTICE,
    DROP_LEGAL_NOTICE,
    EXPIRE_LECTURE_NOTICES,
    LECTURE_NOTICE_BATCH,
    LEGAL_NOTICE_ATTEMPTS,
    MARK_BOT_BLOCKED,
    MARK_LECTURE_NOTICE_SENT,
    MARK_LEGAL_NOTICE_FAILED,
    MARK_LEGAL_NOTICE_SENT,
    PENDING_LECTURE_NOTICES,
    PENDING_LEGAL_NOTICES,
    POSTPONE_LECTURE_NOTICE,
    check_quotas,
    deliver_lecture_notices,
    deliver_legal_notices,
    send_once,
)


class FakeRedis:
    def __init__(self):
        self.keys = {}

    async def get(self, key):
        return self.keys.get(key)

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return False
        self.keys[key] = value
        return True

    async def eval(self, script, count, key, token):
        if self.keys.get(key) == token:
            del self.keys[key]


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


async def test_reset_is_sent_after_long_downtime():
    now = datetime(2026, 10, 27, tzinfo=UTC)
    pool, redis, bot = AsyncMock(), FakeRedis(), AsyncMock()
    pool.fetch.return_value = [
        {
            "id": uuid4(),
            "telegram_chat_id": 11,
            "created_at": now - timedelta(days=20),
            "week_start": now - timedelta(days=3),
            "subscription_until": None,
            "package_left": 0,
        }
    ]
    pool.fetchval.return_value = 0
    await check_quotas(pool, redis, bot, 7200, 36000, now)
    await check_quotas(pool, redis, bot, 7200, 36000, now)
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[1] == "Недельный лимит обработки обновлён."


def legal_rows(*chats):
    link = "https://lecturo.test/legal/ai-transfer"
    return [
        {"id": uuid4(), "telegram_chat_id": chat, "text": "Новая редакция", "link": link}
        for chat in chats
    ]


async def test_legal_notices_are_sent_once_and_failures_are_counted():
    pool, redis, bot = AsyncMock(), FakeRedis(), AsyncMock()
    rows = legal_rows(11, 22, 33, 44)
    pool.fetch.return_value = rows

    async def send(chat_id, text, reply_markup=None):
        method = SendMessage(chat_id=chat_id, text=text)
        if chat_id == 22:
            raise TelegramForbiddenError(method, "blocked")
        if chat_id == 33:
            raise TelegramBadRequest(method, "chat not found")
        if chat_id == 44:
            raise RuntimeError()

    bot.send_message.side_effect = send
    assert await deliver_legal_notices(pool, redis, bot) == 0
    assert pool.fetch.await_args.args == (PENDING_LEGAL_NOTICES, LEGAL_NOTICE_ATTEMPTS)
    assert [call.args for call in pool.execute.await_args_list] == [
        (MARK_LEGAL_NOTICE_SENT, rows[0]["id"]),
        (DROP_LEGAL_NOTICE, rows[1]["id"], LEGAL_NOTICE_ATTEMPTS),
        (DROP_LEGAL_NOTICE, rows[2]["id"], LEGAL_NOTICE_ATTEMPTS),
        (MARK_LEGAL_NOTICE_FAILED, rows[3]["id"]),
    ]
    args, kwargs = bot.send_message.await_args_list[0]
    assert args == (11, "Новая редакция")
    assert kwargs["reply_markup"].inline_keyboard[0][0].web_app.url == rows[0]["link"]
    await deliver_legal_notices(pool, redis, bot)
    assert [call.args[0] for call in bot.send_message.await_args_list].count(11) == 1


async def test_legal_notices_stop_on_retry_after():
    pool, redis, bot = AsyncMock(), FakeRedis(), AsyncMock()
    pool.fetch.return_value = legal_rows(11, 22)
    bot.send_message.side_effect = TelegramRetryAfter(
        SendMessage(chat_id=11, text="Новая редакция"), "flood", 90
    )
    assert await deliver_legal_notices(pool, redis, bot) == 90
    assert bot.send_message.await_count == 1
    pool.execute.assert_not_awaited()


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.committed = False

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.committed = exc[0] is None

    async def fetch(self, query, *args):
        self.calls.append((query, *args))
        return self.rows

    async def execute(self, query, *args):
        self.calls.append((query, *args))


class FakeLecturePool:
    def __init__(self, rows):
        self.connection = FakeConnection(rows)

    def acquire(self):
        return self.connection


def lecture_row(chat, kind="lecture", outcome="ready", started=True, attempts=0):
    return {
        "id": uuid4(),
        "lecture_id": uuid4(),
        "kind": kind,
        "outcome": outcome,
        "attempts": attempts,
        "title": "Матанализ",
        "telegram_chat_id": chat,
        "identity_id": uuid4(),
        "started": started,
    }


async def test_lecture_notices_are_sent_and_closed():
    rows = [
        lecture_row(11),
        lecture_row(22, "regenerate", "failed"),
        lecture_row(33, "quiz", "ready", attempts=2),
        lecture_row(44),
        lecture_row(55, started=False),
        lecture_row(None),
    ]
    pool, bot = FakeLecturePool(rows), AsyncMock()

    async def send(chat_id, text, reply_markup=None):
        method = SendMessage(chat_id=chat_id, text=text)
        if chat_id == 33:
            raise TelegramNetworkError(method, "timeout")
        if chat_id == 44:
            raise TelegramForbiddenError(method, "blocked")

    bot.send_message.side_effect = send
    assert await deliver_lecture_notices(pool, bot, "https://lecturo.test") == 0

    connection = pool.connection
    assert connection.committed
    assert connection.calls == [
        (EXPIRE_LECTURE_NOTICES,),
        (PENDING_LECTURE_NOTICES, LECTURE_NOTICE_BATCH),
        (MARK_LECTURE_NOTICE_SENT, rows[0]["id"]),
        (MARK_LECTURE_NOTICE_SENT, rows[1]["id"]),
        (POSTPONE_LECTURE_NOTICE, rows[2]["id"], 240),
        (MARK_BOT_BLOCKED, rows[3]["identity_id"]),
        (CLOSE_LECTURE_NOTICE, rows[3]["id"]),
        (CLOSE_LECTURE_NOTICE, rows[4]["id"]),
        (CLOSE_LECTURE_NOTICE, rows[5]["id"]),
    ]
    sent = bot.send_message.await_args_list
    assert [call.args for call in sent] == [
        (11, "Лекция «Матанализ» готова."),
        (
            22,
            "Не удалось пересоздать главы и конспект лекции «Матанализ». "
            "Прежний конспект сохранён.",
        ),
        (33, "Квиз по лекции «Матанализ» готов."),
        (44, "Лекция «Матанализ» готова."),
    ]
    assert sent[0].kwargs["reply_markup"].inline_keyboard[0][0].web_app.url == (
        f"https://lecturo.test/lectures/{rows[0]['lecture_id']}"
    )
    assert sent[2].kwargs["reply_markup"].inline_keyboard[0][0].web_app.url == (
        f"https://lecturo.test/lectures/{rows[2]['lecture_id']}/quiz"
    )


async def test_lecture_notice_without_https_has_link_in_text():
    row = lecture_row(11, outcome="failed")
    pool, bot = FakeLecturePool([row]), AsyncMock()
    await deliver_lecture_notices(pool, bot, "http://localhost:8088")
    args, kwargs = bot.send_message.await_args
    assert args[1] == (
        "Не удалось обработать лекцию «Матанализ». Откройте её, чтобы повторить.\n"
        f"http://localhost:8088/lectures/{row['lecture_id']}"
    )
    assert kwargs["reply_markup"] is None


async def test_lecture_notices_wait_on_retry_after_and_close_bad_requests():
    rows = [lecture_row(11), lecture_row(22), lecture_row(33)]
    pool, bot = FakeLecturePool(rows), AsyncMock()

    async def send(chat_id, text, reply_markup=None):
        method = SendMessage(chat_id=chat_id, text=text)
        if chat_id == 11:
            raise TelegramBadRequest(method, "chat not found")
        if chat_id == 22:
            raise TelegramRetryAfter(method, "flood", 30)

    bot.send_message.side_effect = send
    assert await deliver_lecture_notices(pool, bot, "https://lecturo.test") == 30
    assert pool.connection.calls[2:] == [
        (CLOSE_LECTURE_NOTICE, rows[0]["id"]),
        (POSTPONE_LECTURE_NOTICE, rows[1]["id"], 30),
    ]
    assert bot.send_message.await_count == 2
