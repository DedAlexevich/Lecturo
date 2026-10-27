import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
from aiogram import Bot
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.handlers import open_app_markup

logger = logging.getLogger(__name__)

LECTURE_CHAT = """
SELECT u.telegram_chat_id, l.updated_at FROM users u
JOIN lectures l ON l.owner_id = u.id
WHERE u.id = $1 AND l.id = $2 AND u.telegram_chat_id IS NOT NULL
"""

QUOTAS = """
SELECT u.id, u.telegram_chat_id, u.created_at,
       u.quota_week_start + floor(greatest(extract(epoch FROM ($1 - u.quota_week_start)), 0)
                                  / 604800) * interval '7 days' AS week_start,
       (SELECT max(s.ends_at) FROM subscriptions s
        WHERE s.user_id = u.id AND s.starts_at <= $1 AND s.ends_at > $1) AS subscription_until,
       (SELECT coalesce(sum(p.seconds_left), 0) FROM hour_packages p
        WHERE p.user_id = u.id) AS package_left
FROM users u WHERE u.telegram_chat_id IS NOT NULL
"""

WEEKLY_USAGE = """
SELECT coalesce(sum(seconds), 0) FROM usage_entries
WHERE user_id = $1 AND source = 'weekly' AND created_at >= $2
"""


async def send_once(redis: Redis, bot: Bot, key: str, chat_id: int, text: str, markup=None):
    key = f"bot:notification:{key}"
    if await redis.get(key):
        return True
    lock = f"{key}:lock"
    token = str(uuid4())
    if not await redis.set(lock, token, nx=True, ex=120):
        return False
    try:
        if not await redis.get(key):
            await bot.send_message(chat_id, text, reply_markup=markup)
            await redis.set(key, "sent")
        return True
    finally:
        await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            lock,
            token,
        )


async def handle_event(data, pool: asyncpg.Pool, redis: Redis, bot: Bot, public_url: str):
    try:
        event = json.loads(data)
        status = event["status"]
        lecture_id = UUID(event["lecture_id"])
        user_id = UUID(event["user_id"])
    except (ValueError, TypeError, KeyError):
        return
    if status not in ("ready", "failed"):
        return
    row = await pool.fetchrow(LECTURE_CHAT, user_id, lecture_id)
    if row is None:
        return
    key = f"lecture:{lecture_id}:{status}:{row['updated_at'].isoformat()}"
    pending = json.dumps(
        {"chat_id": row["telegram_chat_id"], "status": status, "lecture_id": str(lecture_id)}
    )
    await redis.hset("bot:pending-lectures", key, pending)


async def listen_events(
    pool: asyncpg.Pool, events_redis: Redis, redis: Redis, bot: Bot, public_url: str
):
    while True:
        try:
            async with events_redis.pubsub() as pubsub:
                await pubsub.subscribe("lecture-events")
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            await handle_event(message["data"], pool, redis, bot, public_url)
                        except Exception:
                            logger.exception("Не удалось отправить уведомление о лекции")
        except (RedisError, OSError):
            logger.exception("Не удалось получать события лекций")
            await asyncio.sleep(5)


async def deliver_pending(redis: Redis, bot: Bot, public_url: str):
    for key, data in (await redis.hgetall("bot:pending-lectures")).items():
        try:
            event = json.loads(data)
            key = key.decode() if isinstance(key, bytes) else key
            text = (
                "Лекция готова." if event["status"] == "ready" else "Не удалось обработать лекцию."
            )
            delivered = await send_once(
                redis,
                bot,
                key,
                event["chat_id"],
                text,
                open_app_markup(f"{public_url}/lectures/{event['lecture_id']}"),
            )
            if delivered:
                await redis.hdel("bot:pending-lectures", key)
        except Exception:
            logger.exception("Не удалось отправить уведомление о лекции")


async def delivery_loop(redis: Redis, bot: Bot, public_url: str):
    while True:
        try:
            await deliver_pending(redis, bot, public_url)
        except (RedisError, OSError):
            logger.exception("Не удалось получить ожидающие уведомления")
        await asyncio.sleep(5)


async def check_quotas(
    pool: asyncpg.Pool,
    redis: Redis,
    bot: Bot,
    free_limit: int,
    subscription_limit: int,
    now: datetime | None = None,
):
    now = now or datetime.now(UTC)
    for row in await pool.fetch(QUOTAS, now):
        try:
            user_id = row["id"]
            week_start = row["week_start"]
            until = row["subscription_until"]
            used = await pool.fetchval(WEEKLY_USAGE, user_id, week_start)
            limit = subscription_limit if until else free_limit
            remaining = max(limit - used, 0) + row["package_left"]
            if remaining < 15 * 60:
                await send_once(
                    redis,
                    bot,
                    f"quota-low:{user_id}:{week_start.isoformat()}",
                    row["telegram_chat_id"],
                    "Осталось меньше 15 минут обработки.",
                )
            if week_start > row["created_at"]:
                await send_once(
                    redis,
                    bot,
                    f"quota-reset:{user_id}:{week_start.isoformat()}",
                    row["telegram_chat_id"],
                    "Недельный лимит обработки обновлён.",
                )
            if until and now < until <= now + timedelta(days=3):
                await send_once(
                    redis,
                    bot,
                    f"subscription:{user_id}:{until.isoformat()}",
                    row["telegram_chat_id"],
                    "Подписка закончится в течение трёх дней.",
                )
        except Exception:
            logger.exception("Не удалось проверить уведомления пользователя %s", row["id"])


async def quota_loop(
    pool: asyncpg.Pool, redis: Redis, bot: Bot, free_limit: int, subscription_limit: int
):
    while True:
        try:
            await check_quotas(pool, redis, bot, free_limit, subscription_limit)
        except (asyncpg.PostgresError, OSError, RedisError):
            logger.exception("Не удалось проверить лимиты")
        await asyncio.sleep(3600)
