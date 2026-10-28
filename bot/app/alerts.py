import asyncio
import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

import asyncpg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.notifications import MARK_BOT_BLOCKED, retry_delay

logger = logging.getLogger(__name__)

KINDS = {
    "service_down": "Падение сервисов",
    "queue_stalled": "Очередь обработки",
    "disk_low": "Место на диске",
    "memory_low": "Память",
    "backup": "Бэкапы",
    "payment": "Платежи",
    "webhook_error": "Ошибки вебхуков ЮKassa",
}

MAX_LINES = 5

LOOP_SECONDS = 10

DELIVERY_BATCH = 50

DELIVERY_LEASE_SECONDS = 300

SEND_PAUSE_SECONDS = 0.05

DISPATCH_LOCK_ID = 434_001

TEST_ALERT = "Тестовый алерт Lecturo. Если вы его видите, алерты до вас доходят."

ALERTS_INTRO = (
    "Алерты для администраторов. Нажмите на строку, чтобы включить или выключить её. "
    "Повторы одного типа приходят одним сообщением не чаще раза в {minutes} мин."
)

NOT_ADMIN = "Такой команды нет."

LOCK_ALERT_DISPATCH = "SELECT pg_advisory_xact_lock($1)"

PENDING_ALERT_SIGNALS = """
SELECT id, kind, key, state, text FROM admin_alert_signals
WHERE dispatched_at IS NULL
ORDER BY created_at, id
LIMIT 500
"""

LAST_ALERT_DISPATCH = """
SELECT kind, max(dispatched_at) AS last FROM admin_alert_signals
WHERE state <> 'resolved' AND dispatched_at IS NOT NULL
GROUP BY kind
"""

ALERT_RECIPIENTS = """
SELECT u.id, coalesce(s.muted_kinds, '{}') AS muted_kinds,
       coalesce(s.recoveries, true) AS recoveries
FROM users u
JOIN auth_identities i ON i.user_id = u.id AND i.provider = 'telegram'
LEFT JOIN admin_alert_settings s ON s.user_id = u.id
WHERE u.is_admin AND u.telegram_chat_id IS NOT NULL AND coalesce(s.enabled, true)
  AND i.bot_started_at IS NOT NULL
  AND (i.bot_blocked_at IS NULL OR i.bot_blocked_at <= i.bot_started_at)
"""

QUEUE_ADMIN_ALERTS = """
INSERT INTO admin_alert_deliveries (user_id, text)
SELECT * FROM unnest($1::uuid[], $2::text[])
"""

MARK_ALERT_SIGNALS_DISPATCHED = (
    "UPDATE admin_alert_signals SET dispatched_at = now() WHERE id = ANY($1::uuid[])"
)

EXPIRE_ADMIN_ALERTS = """
UPDATE admin_alert_deliveries SET expired_at = now()
WHERE sent_at IS NULL AND expired_at IS NULL AND created_at < now() - interval '1 day'
"""

PURGE_ADMIN_ALERTS = """
WITH signals AS (
    DELETE FROM admin_alert_signals WHERE dispatched_at < now() - interval '30 days'
)
DELETE FROM admin_alert_deliveries
WHERE coalesce(sent_at, expired_at) < now() - interval '30 days'
"""

CLAIM_ADMIN_ALERTS = """
WITH claimed AS (
    SELECT id, user_id FROM admin_alert_deliveries
    WHERE sent_at IS NULL AND expired_at IS NULL AND next_attempt_at <= now()
    ORDER BY next_attempt_at, created_at
    LIMIT $1
    FOR UPDATE SKIP LOCKED
)
UPDATE admin_alert_deliveries d SET next_attempt_at = now() + make_interval(secs => $2)
FROM claimed c
JOIN users u ON u.id = c.user_id
LEFT JOIN auth_identities i ON i.user_id = c.user_id AND i.provider = 'telegram'
WHERE d.id = c.id
RETURNING d.id, d.text, d.attempts, u.telegram_chat_id, i.id AS identity_id,
          i.bot_started_at IS NOT NULL
              AND (i.bot_blocked_at IS NULL OR i.bot_blocked_at <= i.bot_started_at) AS started
"""

RELEASE_ADMIN_ALERTS = """
UPDATE admin_alert_deliveries SET next_attempt_at = now() + make_interval(secs => $2)
WHERE id = ANY($1::uuid[]) AND sent_at IS NULL AND expired_at IS NULL
"""

MARK_ADMIN_ALERT_SENT = "UPDATE admin_alert_deliveries SET sent_at = now() WHERE id = $1"

POSTPONE_ADMIN_ALERT = """
UPDATE admin_alert_deliveries
SET attempts = attempts + 1, next_attempt_at = now() + make_interval(secs => $2)
WHERE id = $1
"""

CLOSE_ADMIN_ALERT = "UPDATE admin_alert_deliveries SET expired_at = now() WHERE id = $1"

ALERT_ADMIN = """
SELECT u.id, coalesce(nullif(u.email, ''), nullif(u.display_name, ''), u.id::text) AS label,
       coalesce(s.enabled, true) AS enabled,
       coalesce(s.muted_kinds, '{}') AS muted_kinds,
       coalesce(s.recoveries, true) AS recoveries
FROM auth_identities i
JOIN users u ON u.id = i.user_id
LEFT JOIN admin_alert_settings s ON s.user_id = u.id
WHERE i.provider = 'telegram' AND i.provider_user_id = $1 AND u.is_admin
"""

LOCK_ALERT_ADMIN = f"{ALERT_ADMIN}FOR UPDATE OF u"

SAVE_ALERT_SETTINGS = """
INSERT INTO admin_alert_settings (user_id, enabled, muted_kinds, recoveries, updated_at)
VALUES ($1, $2, $3, $4, now())
ON CONFLICT (user_id) DO UPDATE SET
    enabled = EXCLUDED.enabled,
    muted_kinds = EXCLUDED.muted_kinds,
    recoveries = EXCLUDED.recoveries,
    updated_at = now()
"""

RECORD_ALERT_SETTINGS = """
INSERT INTO admin_audit_log
    (actor_id, actor_label, action, target_type, target_id, target_label, details)
VALUES ($1, $2, 'alert_settings_changed', 'user', $1::text, $2, $3::jsonb)
"""

QUEUE_TEST_ALERT = "INSERT INTO admin_alert_deliveries (user_id, text) VALUES ($1, $2)"


@dataclass(frozen=True)
class Recipient:
    user_id: UUID
    muted: frozenset[str]
    recoveries: bool


@dataclass(frozen=True)
class Preferences:
    enabled: bool
    muted: frozenset[str]
    recoveries: bool


def summary_lines(signals) -> list[str]:
    by_key: dict[str, list] = {}
    for signal in signals:
        by_key.setdefault(signal["key"], []).append(signal)
    lines = []
    for repeats in list(by_key.values())[:MAX_LINES]:
        text = repeats[-1]["text"]
        lines.append(text if len(repeats) == 1 else f"{text} (повторов: {len(repeats)})")
    rest = len(by_key) - MAX_LINES
    if rest > 0:
        lines.append(f"И ещё {rest}")
    return lines


def alert_message(kind: str, signals, recovery: bool) -> str:
    title = KINDS.get(kind, kind)
    head = f"Восстановлено: {title}" if recovery else f"Алерт: {title}"
    return "\n".join([head, *summary_lines(signals)])


def plan_dispatch(
    signals,
    last_sent: dict[str, datetime],
    recipients: list[Recipient],
    now: datetime,
    interval: timedelta,
) -> tuple[list[UUID], list[tuple[UUID, str]]]:
    by_kind: dict[str, list] = {}
    for signal in signals:
        by_kind.setdefault(signal["kind"], []).append(signal)
    dispatched: list[UUID] = []
    deliveries: list[tuple[UUID, str]] = []
    for kind, items in by_kind.items():
        problems = [item for item in items if item["state"] != "resolved"]
        recoveries = [item for item in items if item["state"] == "resolved"]
        last = last_sent.get(kind)
        if not recoveries and last is not None and now - last < interval:
            continue
        dispatched.extend(item["id"] for item in items)
        if problems:
            text = alert_message(kind, problems, recovery=False)
            deliveries.extend(
                (recipient.user_id, text) for recipient in recipients if kind not in recipient.muted
            )
        if recoveries:
            text = alert_message(kind, recoveries, recovery=True)
            deliveries.extend(
                (recipient.user_id, text)
                for recipient in recipients
                if kind not in recipient.muted and recipient.recoveries
            )
    return dispatched, deliveries


async def dispatch_admin_alerts(pool: asyncpg.Pool, interval: timedelta) -> int:
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(LOCK_ALERT_DISPATCH, DISPATCH_LOCK_ID)
        signals = await connection.fetch(PENDING_ALERT_SIGNALS)
        if not signals:
            return 0
        now = await connection.fetchval("SELECT now()")
        last_sent = {
            row["kind"]: row["last"] for row in await connection.fetch(LAST_ALERT_DISPATCH)
        }
        recipients = [
            Recipient(row["id"], frozenset(row["muted_kinds"]), row["recoveries"])
            for row in await connection.fetch(ALERT_RECIPIENTS)
        ]
        dispatched, deliveries = plan_dispatch(signals, last_sent, recipients, now, interval)
        if deliveries:
            await connection.execute(
                QUEUE_ADMIN_ALERTS,
                [user_id for user_id, _ in deliveries],
                [text for _, text in deliveries],
            )
        if dispatched:
            await connection.execute(MARK_ALERT_SIGNALS_DISPATCHED, dispatched)
        return len(deliveries)


async def deliver_admin_alerts(pool: asyncpg.Pool, bot: Bot) -> int:
    await pool.execute(EXPIRE_ADMIN_ALERTS)
    rows = await pool.fetch(CLAIM_ADMIN_ALERTS, DELIVERY_BATCH, DELIVERY_LEASE_SECONDS)
    for index, row in enumerate(rows):
        if not row["started"] or row["telegram_chat_id"] is None:
            await pool.execute(CLOSE_ADMIN_ALERT, row["id"])
            continue
        try:
            await bot.send_message(row["telegram_chat_id"], row["text"])
        except TelegramRetryAfter as error:
            await pool.execute(POSTPONE_ADMIN_ALERT, row["id"], error.retry_after)
            rest = [later["id"] for later in rows[index + 1 :]]
            if rest:
                await pool.execute(RELEASE_ADMIN_ALERTS, rest, error.retry_after)
            return error.retry_after
        except TelegramForbiddenError:
            await pool.execute(MARK_BOT_BLOCKED, row["identity_id"])
            await pool.execute(CLOSE_ADMIN_ALERT, row["id"])
            continue
        except TelegramBadRequest:
            logger.warning("Telegram отклонил алерт %s", row["id"])
            await pool.execute(CLOSE_ADMIN_ALERT, row["id"])
            continue
        except Exception:
            logger.exception("Не удалось отправить алерт %s", row["id"])
            await pool.execute(POSTPONE_ADMIN_ALERT, row["id"], retry_delay(row["attempts"]))
            continue
        await pool.execute(MARK_ADMIN_ALERT_SENT, row["id"])
        await asyncio.sleep(SEND_PAUSE_SECONDS)
    return 0


async def admin_alerts_loop(pool: asyncpg.Pool, bot: Bot, interval: timedelta):
    while True:
        pause = 0
        try:
            await dispatch_admin_alerts(pool, interval)
            pause = await deliver_admin_alerts(pool, bot)
            await pool.execute(PURGE_ADMIN_ALERTS)
        except Exception:
            logger.exception("Не удалось разослать алерты администраторам")
        await asyncio.sleep(max(pause, LOOP_SECONDS))


def switch(on: bool) -> str:
    return "вкл" if on else "выкл"


def alerts_markup(preferences: Preferences) -> InlineKeyboardMarkup:
    def button(text: str, data: str) -> list[InlineKeyboardButton]:
        return [InlineKeyboardButton(text=text, callback_data=data)]

    rows = [button(f"Все алерты: {switch(preferences.enabled)}", "alerts:enabled")]
    rows += [
        button(f"{title}: {switch(kind not in preferences.muted)}", f"alerts:kind:{kind}")
        for kind, title in KINDS.items()
    ]
    rows.append(
        button(f"Сообщения о восстановлении: {switch(preferences.recoveries)}", "alerts:recoveries")
    )
    rows.append(button("Прислать тестовый алерт", "alerts:test"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def toggled(preferences: Preferences, action: str) -> Preferences | None:
    if action == "alerts:enabled":
        return replace(preferences, enabled=not preferences.enabled)
    if action == "alerts:recoveries":
        return replace(preferences, recoveries=not preferences.recoveries)
    kind = action.removeprefix("alerts:kind:")
    if action.startswith("alerts:kind:") and kind in KINDS:
        return replace(preferences, muted=preferences.muted ^ {kind})
    return None


def preferences_of(row) -> Preferences:
    return Preferences(row["enabled"], frozenset(row["muted_kinds"]), row["recoveries"])


async def save_preferences(connection: asyncpg.Connection, admin, preferences: Preferences) -> None:
    muted = [kind for kind in KINDS if kind in preferences.muted]
    await connection.execute(
        SAVE_ALERT_SETTINGS, admin["id"], preferences.enabled, muted, preferences.recoveries
    )
    details = {
        "source": "bot",
        "enabled": preferences.enabled,
        "kinds": [kind for kind in KINDS if kind not in preferences.muted],
        "recoveries": preferences.recoveries,
    }
    await connection.execute(
        RECORD_ALERT_SETTINGS, admin["id"], admin["label"], json.dumps(details)
    )


async def handle_alert_action(
    pool: asyncpg.Pool, telegram_id: int, action: str
) -> tuple[Preferences | None, bool]:
    async with pool.acquire() as connection, connection.transaction():
        admin = await connection.fetchrow(LOCK_ALERT_ADMIN, str(telegram_id))
        if admin is None:
            return None, False
        preferences = preferences_of(admin)
        if action == "alerts:test":
            await connection.execute(QUEUE_TEST_ALERT, admin["id"], TEST_ALERT)
            return preferences, True
        changed = toggled(preferences, action)
        if changed is None:
            return preferences, False
        await save_preferences(connection, admin, changed)
        return changed, False


def build_alerts_router(pool: asyncpg.Pool | None, interval: timedelta) -> Router:
    router = Router()
    intro = ALERTS_INTRO.format(minutes=int(interval.total_seconds() // 60))

    @router.message(Command("alerts"))
    async def alerts(message: Message) -> None:
        admin = None
        if pool is not None and message.from_user is not None:
            admin = await pool.fetchrow(ALERT_ADMIN, str(message.from_user.id))
        if admin is None:
            await message.answer(NOT_ADMIN)
            return
        await message.answer(intro, reply_markup=alerts_markup(preferences_of(admin)))

    @router.callback_query(F.data.startswith("alerts:"))
    async def alert_action(callback: CallbackQuery) -> None:
        if pool is None:
            await callback.answer()
            return
        preferences, tested = await handle_alert_action(pool, callback.from_user.id, callback.data)
        if preferences is None:
            await callback.answer("Нет доступа")
            if isinstance(callback.message, Message):
                await callback.message.edit_reply_markup(reply_markup=None)
            return
        if tested:
            await callback.answer("Тестовый алерт придёт через несколько секунд")
            return
        await callback.answer("Сохранено")
        if isinstance(callback.message, Message):
            try:
                await callback.message.edit_reply_markup(reply_markup=alerts_markup(preferences))
            except TelegramBadRequest:
                logger.warning("Не удалось обновить кнопки настроек алертов")

    return router
