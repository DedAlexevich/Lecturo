import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup
from redis.asyncio import Redis

from app.handlers import open_app_markup

logger = logging.getLogger(__name__)

QUOTAS = """
WITH recipients AS (
    SELECT u.id, u.telegram_chat_id, u.created_at,
           u.quota_week_start
               + floor(greatest(extract(epoch FROM ($1 - u.quota_week_start)), 0) / 604800)
               * interval '7 days' AS week_start
    FROM users u WHERE u.telegram_chat_id IS NOT NULL
),
usage AS (
    SELECT r.id,
           coalesce(sum(e.seconds) FILTER (
               WHERE e.source = 'weekly' AND e.created_at >= r.week_start
           ), 0) AS used,
           bool_or(e.created_at < r.week_start) AS active_last_week
    FROM recipients r
    JOIN usage_entries e
        ON e.user_id = r.id AND e.created_at >= r.week_start - interval '7 days'
    GROUP BY r.id
)
SELECT r.id, r.telegram_chat_id, r.created_at, r.week_start,
       coalesce(us.used, 0) AS used,
       coalesce(us.active_last_week, false) AS active_last_week,
       (SELECT max(s.ends_at) FROM subscriptions s
        WHERE s.user_id = r.id AND s.starts_at <= $1 AND s.ends_at > $1) AS subscription_until,
       (SELECT coalesce(sum(p.seconds_left), 0) FROM hour_packages p
        WHERE p.user_id = r.id) AS package_left
FROM recipients r LEFT JOIN usage us ON us.id = r.id
"""

QUOTA_INTERVAL_SECONDS = 3600

UNREACHABLE_CHAT_TTL = timedelta(days=7)

LEGAL_NOTICE_ATTEMPTS = 5

PENDING_LEGAL_NOTICES = """
SELECT n.id, u.telegram_chat_id, n.text, n.link FROM legal_notices n
JOIN users u ON u.id = n.user_id
WHERE n.channel = 'telegram' AND n.sent_at IS NULL AND u.telegram_chat_id IS NOT NULL
  AND n.attempts < $1
  AND (n.attempted_at IS NULL OR n.attempted_at < now() - interval '30 minutes')
ORDER BY n.attempts, n.created_at, n.id LIMIT 100
"""

MARK_LEGAL_NOTICE_SENT = (
    "UPDATE legal_notices SET sent_at = now(), attempted_at = now() WHERE id = $1"
)

MARK_LEGAL_NOTICE_FAILED = (
    "UPDATE legal_notices SET attempts = attempts + 1, attempted_at = now() WHERE id = $1"
)

DROP_LEGAL_NOTICE = "UPDATE legal_notices SET attempts = $2, attempted_at = now() WHERE id = $1"

SEND_PAUSE_SECONDS = 0.05

LEGAL_NOTICE_TTL = timedelta(days=30)

QUOTA_NOTICE_TTL = timedelta(days=14)

LECTURE_NOTICE_PAUSE_SECONDS = 0.05

LEGAL_NOTICE_INTERVAL_SECONDS = 60

LECTURE_NOTICE_BATCH = 50

LECTURE_NOTICE_INTERVAL_SECONDS = 5

LECTURE_NOTICE_MAX_DELAY_SECONDS = 3600

EXPIRE_LECTURE_NOTICES = """
UPDATE notification_events SET expired_at = now()
WHERE sent_at IS NULL AND expired_at IS NULL AND created_at < now() - interval '7 days'
"""

LECTURE_NOTICE_LEASE_SECONDS = 300

CLAIM_LECTURE_NOTICES = """
WITH claimed AS (
    SELECT id, lecture_id, user_id FROM notification_events
    WHERE sent_at IS NULL AND expired_at IS NULL AND next_attempt_at <= now()
    ORDER BY next_attempt_at, created_at
    LIMIT $1
    FOR UPDATE SKIP LOCKED
)
UPDATE notification_events e SET next_attempt_at = now() + make_interval(secs => $2)
FROM claimed c
JOIN lectures l ON l.id = c.lecture_id
JOIN users u ON u.id = c.user_id
LEFT JOIN auth_identities i ON i.user_id = c.user_id AND i.provider = 'telegram'
WHERE e.id = c.id
RETURNING e.id, e.lecture_id, e.kind, e.outcome, e.attempts, l.title, u.telegram_chat_id,
          i.id AS identity_id,
          i.bot_started_at IS NOT NULL
              AND (i.bot_blocked_at IS NULL OR i.bot_blocked_at <= i.bot_started_at) AS started
"""

RELEASE_LECTURE_NOTICES = """
UPDATE notification_events SET next_attempt_at = now() + make_interval(secs => $2)
WHERE id = ANY($1::uuid[]) AND sent_at IS NULL AND expired_at IS NULL
"""

MARK_LECTURE_NOTICE_SENT = "UPDATE notification_events SET sent_at = now() WHERE id = $1"

POSTPONE_LECTURE_NOTICE = """
UPDATE notification_events
SET attempts = attempts + 1, next_attempt_at = now() + make_interval(secs => $2)
WHERE id = $1
"""

CLOSE_LECTURE_NOTICE = "UPDATE notification_events SET expired_at = now() WHERE id = $1"

MARK_BOT_BLOCKED = "UPDATE auth_identities SET bot_blocked_at = now() WHERE id = $1"

LECTURE_NOTICE_TEXTS = {
    ("lecture", "ready"): "Лекция «{title}» готова.",
    ("lecture", "failed"): "Не удалось обработать лекцию «{title}». Откройте её, чтобы повторить.",
    ("regenerate", "ready"): "Главы и конспект лекции «{title}» пересозданы.",
    ("regenerate", "failed"): (
        "Не удалось пересоздать главы и конспект лекции «{title}». Прежний конспект сохранён."
    ),
    ("quiz", "ready"): "Квиз по лекции «{title}» готов.",
    ("quiz", "failed"): "Не удалось создать квиз по лекции «{title}».",
}


async def send_once(
    redis: Redis,
    bot: Bot,
    key: str,
    chat_id: int,
    text: str,
    ttl: timedelta,
    markup=None,
):
    key = f"bot:notification:{key}"
    if await redis.get(key):
        return True
    lock = f"{key}:lock"
    token = str(uuid4())
    if not await redis.set(lock, token, nx=True, ex=120):
        return False
    try:
        if await redis.get(key):
            return True
        await bot.send_message(chat_id, text, reply_markup=markup)
        await redis.set(key, "sent", ex=ttl)
    finally:
        await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            lock,
            token,
        )
    await asyncio.sleep(SEND_PAUSE_SECONDS)
    return True


def lecture_notice(row, public_url: str) -> tuple[str, InlineKeyboardMarkup | None]:
    text = LECTURE_NOTICE_TEXTS[(row["kind"], row["outcome"])].format(title=row["title"])
    link = f"{public_url}/lectures/{row['lecture_id']}"
    if row["kind"] == "quiz" and row["outcome"] == "ready":
        link += "/quiz"
    markup = open_app_markup(link)
    if markup is None:
        text = f"{text}\n{link}"
    return text, markup


def retry_delay(attempts: int) -> int:
    return min(60 * 2**attempts, LECTURE_NOTICE_MAX_DELAY_SECONDS)


async def deliver_lecture_notices(pool: asyncpg.Pool, bot: Bot, public_url: str) -> int:
    await pool.execute(EXPIRE_LECTURE_NOTICES)
    rows = await pool.fetch(
        CLAIM_LECTURE_NOTICES, LECTURE_NOTICE_BATCH, LECTURE_NOTICE_LEASE_SECONDS
    )
    for index, row in enumerate(rows):
        if not row["started"] or row["telegram_chat_id"] is None:
            await pool.execute(CLOSE_LECTURE_NOTICE, row["id"])
            continue
        text, markup = lecture_notice(row, public_url)
        try:
            await bot.send_message(row["telegram_chat_id"], text, reply_markup=markup)
        except TelegramRetryAfter as error:
            await pool.execute(POSTPONE_LECTURE_NOTICE, row["id"], error.retry_after)
            rest = [later["id"] for later in rows[index + 1 :]]
            if rest:
                await pool.execute(RELEASE_LECTURE_NOTICES, rest, error.retry_after)
            return error.retry_after
        except TelegramForbiddenError:
            await pool.execute(MARK_BOT_BLOCKED, row["identity_id"])
            await pool.execute(CLOSE_LECTURE_NOTICE, row["id"])
            continue
        except TelegramBadRequest:
            logger.warning("Telegram отклонил уведомление %s", row["id"])
            await pool.execute(CLOSE_LECTURE_NOTICE, row["id"])
            continue
        except Exception:
            logger.exception("Не удалось отправить уведомление %s", row["id"])
            await pool.execute(POSTPONE_LECTURE_NOTICE, row["id"], retry_delay(row["attempts"]))
            continue
        await pool.execute(MARK_LECTURE_NOTICE_SENT, row["id"])
        await asyncio.sleep(LECTURE_NOTICE_PAUSE_SECONDS)
    return 0


async def lecture_notices_loop(pool: asyncpg.Pool, bot: Bot, public_url: str):
    while True:
        pause = 0
        try:
            pause = await deliver_lecture_notices(pool, bot, public_url)
        except Exception:
            logger.exception("Не удалось получить уведомления о лекциях")
        await asyncio.sleep(max(pause, LECTURE_NOTICE_INTERVAL_SECONDS))


async def deliver_legal_notices(pool: asyncpg.Pool, redis: Redis, bot: Bot) -> int:
    for row in await pool.fetch(PENDING_LEGAL_NOTICES, LEGAL_NOTICE_ATTEMPTS):
        try:
            delivered = await send_once(
                redis,
                bot,
                f"legal:{row['id']}",
                row["telegram_chat_id"],
                row["text"],
                LEGAL_NOTICE_TTL,
                open_app_markup(row["link"]),
            )
        except TelegramRetryAfter as error:
            return error.retry_after
        except (TelegramForbiddenError, TelegramBadRequest):
            await pool.execute(DROP_LEGAL_NOTICE, row["id"], LEGAL_NOTICE_ATTEMPTS)
            continue
        except Exception:
            logger.exception("Не удалось отправить уведомление о новой редакции документа")
            await pool.execute(MARK_LEGAL_NOTICE_FAILED, row["id"])
            continue
        if delivered:
            await pool.execute(MARK_LEGAL_NOTICE_SENT, row["id"])
    return 0


async def legal_notices_loop(pool: asyncpg.Pool, redis: Redis, bot: Bot):
    while True:
        pause = 0
        try:
            pause = await deliver_legal_notices(pool, redis, bot)
        except Exception:
            logger.exception("Не удалось получить уведомления о новых редакциях документов")
        await asyncio.sleep(max(pause, LEGAL_NOTICE_INTERVAL_SECONDS))


async def check_quotas(
    pool: asyncpg.Pool,
    redis: Redis,
    bot: Bot,
    free_limit: int,
    subscription_limit: int,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    for row in await pool.fetch(QUOTAS, now):
        user_id = row["id"]
        unreachable = f"bot:notification:unreachable:{user_id}"
        try:
            if await redis.get(unreachable):
                continue
            week_start = row["week_start"]
            until = row["subscription_until"]
            limit = subscription_limit if until else free_limit
            remaining = max(limit - row["used"], 0) + row["package_left"]
            if remaining < 15 * 60:
                await send_once(
                    redis,
                    bot,
                    f"quota-low:{user_id}:{week_start.isoformat()}",
                    row["telegram_chat_id"],
                    "Осталось меньше 15 минут обработки.",
                    QUOTA_NOTICE_TTL,
                )
            if week_start > row["created_at"] and row["active_last_week"]:
                await send_once(
                    redis,
                    bot,
                    f"quota-reset:{user_id}:{week_start.isoformat()}",
                    row["telegram_chat_id"],
                    "Недельный лимит обработки обновлён.",
                    QUOTA_NOTICE_TTL,
                )
            if until and now < until <= now + timedelta(days=3):
                await send_once(
                    redis,
                    bot,
                    f"subscription:{user_id}:{until.isoformat()}",
                    row["telegram_chat_id"],
                    "Подписка закончится в течение трёх дней.",
                    until + timedelta(days=7) - now,
                )
        except TelegramRetryAfter as error:
            return error.retry_after
        except (TelegramForbiddenError, TelegramBadRequest):
            await redis.set(unreachable, "1", ex=UNREACHABLE_CHAT_TTL)
        except Exception:
            logger.exception("Не удалось проверить уведомления пользователя %s", user_id)
    return 0


async def quota_loop(
    pool: asyncpg.Pool, redis: Redis, bot: Bot, free_limit: int, subscription_limit: int
):
    while True:
        pause = 0
        try:
            pause = await check_quotas(pool, redis, bot, free_limit, subscription_limit)
        except Exception:
            logger.exception("Не удалось проверить лимиты")
        await asyncio.sleep(pause or QUOTA_INTERVAL_SECONDS)
