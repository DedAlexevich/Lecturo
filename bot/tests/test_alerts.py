import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from app import alerts
from app.alerts import (
    CLAIM_ADMIN_ALERTS,
    CLOSE_ADMIN_ALERT,
    DELIVERY_BATCH,
    DELIVERY_LEASE_SECONDS,
    KINDS,
    MARK_ADMIN_ALERT_SENT,
    POSTPONE_ADMIN_ALERT,
    RELEASE_ADMIN_ALERTS,
    TEST_ALERT,
    Preferences,
    Recipient,
    alert_message,
    alerts_markup,
    deliver_admin_alerts,
    dispatch_admin_alerts,
    handle_alert_action,
    plan_dispatch,
    toggled,
)
from app.notifications import MARK_BOT_BLOCKED

SCHEMA_CHECK = os.environ.get("BOT_SCHEMA_CHECK") == "1"

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
INTERVAL = timedelta(minutes=15)


def signal(kind: str, key: str, state: str = "firing", text: str | None = None) -> dict:
    return {"id": uuid4(), "kind": kind, "key": key, "state": state, "text": text or key}


def recipient(muted: set[str] | None = None, recoveries: bool = True) -> Recipient:
    return Recipient(uuid4(), frozenset(muted or ()), recoveries)


def test_muted_kind_is_not_delivered():
    first, second = recipient(), recipient({"disk_low"})
    signals = [signal("disk_low", "disk", text="Диск занят на 91%")]

    dispatched, deliveries = plan_dispatch(signals, {}, [first, second], NOW, INTERVAL)

    assert dispatched == [signals[0]["id"]]
    assert deliveries == [(first.user_id, "Алерт: Место на диске\nДиск занят на 91%")]


def test_repeats_are_merged_into_one_message():
    signals = [
        signal("webhook_error", "yk-1", "event", "Вебхук yk-1: ошибка"),
        signal("webhook_error", "yk-1", "event", "Вебхук yk-1: ошибка"),
        signal("webhook_error", "yk-2", "event", "Вебхук yk-2: ошибка"),
    ]
    admin = recipient()

    dispatched, deliveries = plan_dispatch(signals, {}, [admin], NOW, INTERVAL)

    assert len(dispatched) == 3
    assert deliveries == [
        (
            admin.user_id,
            "Алерт: Ошибки вебхуков ЮKassa\nВебхук yk-1: ошибка (повторов: 2)\nВебхук yk-2: ошибка",
        )
    ]


def test_long_summary_is_cut():
    signals = [signal("payment", f"payment:{index}", "event") for index in range(8)]

    text = alert_message("payment", signals, recovery=False)

    assert text.splitlines()[-1] == "И ещё 3"
    assert len(text.splitlines()) == alerts.MAX_LINES + 2


def test_long_message_fits_telegram_limit():
    signals = [signal("service_down", "unit", "event", "x" * 10_000)]

    assert len(alert_message("service_down", signals, recovery=False)) == alerts.MESSAGE_LIMIT


def test_kind_waits_for_interval_and_keeps_signals():
    signals = [signal("payment", "payment:1", "event")]
    last_sent = {"payment": NOW - timedelta(minutes=5)}

    dispatched, deliveries = plan_dispatch(signals, last_sent, [recipient()], NOW, INTERVAL)

    assert dispatched == []
    assert deliveries == []
    later = plan_dispatch(signals, last_sent, [recipient()], NOW + INTERVAL, INTERVAL)
    assert later[0] == [signals[0]["id"]]


def test_interval_is_counted_per_kind():
    signals = [signal("payment", "payment:1", "event"), signal("disk_low", "disk")]
    last_sent = {"payment": NOW - timedelta(minutes=1)}

    dispatched, deliveries = plan_dispatch(signals, last_sent, [recipient()], NOW, INTERVAL)

    assert dispatched == [signals[1]["id"]]
    assert [text.splitlines()[0] for _, text in deliveries] == ["Алерт: Место на диске"]


def test_recovery_is_sent_without_waiting():
    signals = [signal("service_down", "health", "resolved", "Lecturo снова работает")]
    last_sent = {"service_down": NOW - timedelta(minutes=1)}
    wants, silent = recipient(), recipient(recoveries=False)

    dispatched, deliveries = plan_dispatch(signals, last_sent, [wants, silent], NOW, INTERVAL)

    assert dispatched == [signals[0]["id"]]
    assert deliveries == [
        (wants.user_id, "Восстановлено: Падение сервисов\nLecturo снова работает")
    ]


def test_no_recipients_still_marks_signals():
    signals = [signal("memory_low", "memory")]

    dispatched, deliveries = plan_dispatch(signals, {}, [], NOW, INTERVAL)

    assert dispatched == [signals[0]["id"]]
    assert deliveries == []


def test_toggles():
    preferences = Preferences(True, frozenset(), True)

    assert toggled(preferences, "alerts:enabled").enabled is False
    assert toggled(preferences, "alerts:recoveries").recoveries is False
    assert toggled(preferences, "alerts:kind:payment").muted == {"payment"}
    assert (
        toggled(Preferences(True, frozenset({"payment"}), True), "alerts:kind:payment").muted
        == frozenset()
    )
    assert toggled(preferences, "alerts:kind:weather") is None
    assert toggled(preferences, "alerts:other") is None


def test_markup_shows_every_kind():
    markup = alerts_markup(Preferences(True, frozenset({"payment"}), False))

    texts = [row[0].text for row in markup.inline_keyboard]
    data = [row[0].callback_data for row in markup.inline_keyboard]
    assert texts[0] == "Все алерты: вкл"
    assert "Платежи: выкл" in texts
    assert "Сообщения о восстановлении: выкл" in texts
    assert data[-1] == "alerts:test"
    assert {f"alerts:kind:{kind}" for kind in KINDS} <= set(data)


def delivery_rows(*chats, started=True):
    return [
        {
            "id": uuid4(),
            "text": "Алерт",
            "attempts": 0,
            "telegram_chat_id": chat,
            "identity_id": uuid4(),
            "started": started,
        }
        for chat in chats
    ]


async def test_delivery_outcomes(monkeypatch):
    monkeypatch.setattr(alerts, "SEND_PAUSE_SECONDS", 0)
    pool, bot = AsyncMock(), AsyncMock()
    rows = delivery_rows(11, 22, 33, 44)
    pool.fetch.return_value = rows

    async def send(chat_id, text):
        method = SendMessage(chat_id=chat_id, text=text)
        if chat_id == 22:
            raise TelegramForbiddenError(method, "blocked")
        if chat_id == 33:
            raise TelegramBadRequest(method, "chat not found")
        if chat_id == 44:
            raise RuntimeError()

    bot.send_message.side_effect = send

    assert await deliver_admin_alerts(pool, bot) == 0

    assert pool.fetch.await_args.args == (
        CLAIM_ADMIN_ALERTS,
        DELIVERY_BATCH,
        DELIVERY_LEASE_SECONDS,
    )
    assert [call.args for call in pool.execute.await_args_list[1:]] == [
        (MARK_ADMIN_ALERT_SENT, rows[0]["id"]),
        (MARK_BOT_BLOCKED, rows[1]["identity_id"]),
        (CLOSE_ADMIN_ALERT, rows[1]["id"]),
        (CLOSE_ADMIN_ALERT, rows[2]["id"]),
        (POSTPONE_ADMIN_ALERT, rows[3]["id"], 60),
    ]


async def test_delivery_skips_admin_without_started_bot():
    pool, bot = AsyncMock(), AsyncMock()
    rows = delivery_rows(11, started=False)
    pool.fetch.return_value = rows

    await deliver_admin_alerts(pool, bot)

    bot.send_message.assert_not_awaited()
    assert pool.execute.await_args.args == (CLOSE_ADMIN_ALERT, rows[0]["id"])


async def test_delivery_stops_on_retry_after():
    pool, bot = AsyncMock(), AsyncMock()
    rows = delivery_rows(11, 22, 33)
    pool.fetch.return_value = rows
    bot.send_message.side_effect = TelegramRetryAfter(
        SendMessage(chat_id=11, text="Алерт"), "flood", 30
    )

    assert await deliver_admin_alerts(pool, bot) == 30

    assert bot.send_message.await_count == 1
    assert [call.args for call in pool.execute.await_args_list[1:]] == [
        (POSTPONE_ADMIN_ALERT, rows[0]["id"], 30),
        (RELEASE_ADMIN_ALERTS, [rows[1]["id"], rows[2]["id"]], 30),
    ]


@pytest.fixture
async def pool():
    if not SCHEMA_CHECK:
        pytest.skip("BOT_SCHEMA_CHECK не задан")
    pool = await asyncpg.create_pool(min_size=1, max_size=2)
    await pool.execute("DELETE FROM admin_alert_signals")
    users: list = []
    yield pool, users
    await pool.execute("DELETE FROM admin_alert_signals")
    await pool.execute("DELETE FROM users WHERE id = ANY($1::uuid[])", users)
    await pool.close()


async def create_admin(pool, users, telegram_id: int, is_admin: bool = True, started=True):
    user_id = await pool.fetchval(
        "INSERT INTO users (display_name, email, is_admin, telegram_chat_id) "
        "VALUES ('Админ', $1, $2, $3) RETURNING id",
        f"{uuid4().hex}@example.org",
        is_admin,
        telegram_id,
    )
    users.append(user_id)
    await pool.execute(
        "INSERT INTO auth_identities (user_id, provider, provider_user_id, data, bot_started_at) "
        "VALUES ($1, 'telegram', $2, '{}', CASE WHEN $3 THEN now() END)",
        user_id,
        str(telegram_id),
        started,
    )
    return user_id


async def queued_texts(pool, user_id) -> list[str]:
    rows = await pool.fetch(
        "SELECT text FROM admin_alert_deliveries WHERE user_id = $1 ORDER BY created_at", user_id
    )
    return [row["text"] for row in rows]


async def test_signals_reach_only_subscribed_admins(pool):
    pool, users = pool
    base = 7_000_000_000 + int(uuid4().int % 1_000_000)
    subscribed = await create_admin(pool, users, base + 1)
    muted = await create_admin(pool, users, base + 2)
    not_started = await create_admin(pool, users, base + 3, started=False)
    regular = await create_admin(pool, users, base + 4, is_admin=False)
    preferences, _ = await handle_alert_action(pool, base + 2, "alerts:kind:disk_low")
    assert preferences.muted == {"disk_low"}
    assert (await handle_alert_action(pool, base + 4, "alerts:enabled"))[0] is None
    await pool.execute(
        "INSERT INTO admin_alert_signals (kind, key, state, text) "
        "VALUES ('disk_low', 'disk', 'firing', 'Диск занят на 91%')"
    )

    assert await dispatch_admin_alerts(pool, INTERVAL) == 1
    assert await dispatch_admin_alerts(pool, INTERVAL) == 0

    assert await queued_texts(pool, subscribed) == ["Алерт: Место на диске\nДиск занят на 91%"]
    for user_id in (muted, not_started, regular):
        assert await queued_texts(pool, user_id) == []
    action = await pool.fetchval(
        "SELECT details->>'source' FROM admin_audit_log WHERE actor_id = $1", muted
    )
    assert action == "bot"
    await pool.execute("DELETE FROM admin_audit_log WHERE actor_id = ANY($1::uuid[])", users)


async def test_test_alert_from_bot_is_queued(pool):
    pool, users = pool
    telegram_id = 7_100_000_000 + int(uuid4().int % 1_000_000)
    admin = await create_admin(pool, users, telegram_id)

    preferences, tested = await handle_alert_action(pool, telegram_id, "alerts:test")

    assert tested
    assert preferences == Preferences(True, frozenset(), True)
    assert await queued_texts(pool, admin) == [TEST_ALERT]
