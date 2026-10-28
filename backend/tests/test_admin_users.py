import random
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import (
    AdminAuditEntry,
    AuthIdentity,
    HourPackage,
    Lecture,
    LectureStatus,
    Payment,
    PaymentKind,
    PaymentStatus,
    ProcessingStep,
    SourceType,
    StepName,
    StepStatus,
    Subscription,
    UsageEntry,
    UsageSource,
    User,
)
from app.services.admin_users import MOSCOW, collect_stats
from app.services.auth import hash_password
from tests.test_admin import MakeUser, headers, make_user

__all__ = ["make_user"]

PASSWORD = "correct-horse-battery"


@pytest.fixture
async def admin(make_user: MakeUser) -> AsyncIterator[User]:
    user = await make_user(is_admin=True)
    yield user
    async with SessionLocal() as session:
        await session.execute(delete(AdminAuditEntry).where(AdminAuditEntry.actor_id == user.id))
        await session.commit()


async def actions_of(admin: User) -> list[AdminAuditEntry]:
    async with SessionLocal() as session:
        entries = await session.scalars(
            select(AdminAuditEntry)
            .where(AdminAuditEntry.actor_id == admin.id)
            .order_by(AdminAuditEntry.created_at)
        )
        return list(entries.all())


async def with_password(user: User) -> User:
    async with SessionLocal() as session:
        stored = await session.get(User, user.id)
        stored.password_hash = hash_password(PASSWORD)
        await session.commit()
        return stored


async def test_regular_user_gets_404(client: AsyncClient, make_user: MakeUser):
    regular = await make_user()

    search = await client.get(
        "/api/v1/admin/users", params={"q": "admin"}, headers=headers(regular)
    )
    card = await client.get(f"/api/v1/admin/users/{regular.id}", headers=headers(regular))
    hours = await client.post(
        f"/api/v1/admin/users/{regular.id}/hours",
        json={"hours": 5, "reason": "сам себе"},
        headers=headers(regular),
    )
    stats = await client.get("/api/v1/admin/stats", headers=headers(regular))

    assert [r.status_code for r in (search, card, hours, stats)] == [404, 404, 404, 404]


async def test_search_by_email_telegram_id_and_username(
    client: AsyncClient, make_user: MakeUser, admin: User
):
    telegram_id = random.randint(10**9, 10**10)
    by_email = await make_user()
    by_telegram = await make_user(telegram_id=telegram_id)
    username = f"student_{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as session:
        identity = await session.scalar(
            select(AuthIdentity).where(AuthIdentity.user_id == by_telegram.id)
        )
        identity.data = {"username": username}
        await session.commit()

    found_email = await client.get(
        "/api/v1/admin/users",
        params={"q": by_email.email.split("@")[0].upper()},
        headers=headers(admin),
    )
    found_id = await client.get(
        "/api/v1/admin/users", params={"q": str(telegram_id)}, headers=headers(admin)
    )
    found_name = await client.get(
        "/api/v1/admin/users", params={"q": f"@{username.upper()}"}, headers=headers(admin)
    )
    nothing = await client.get("/api/v1/admin/users", params={"q": "%_"}, headers=headers(admin))

    assert [item["id"] for item in found_email.json()] == [str(by_email.id)]
    assert [item["id"] for item in found_id.json()] == [str(by_telegram.id)]
    assert [item["id"] for item in found_name.json()] == [str(by_telegram.id)]
    assert nothing.json() == []
    assert set(found_email.json()[0]) == {
        "id",
        "email",
        "display_name",
        "created_at",
        "is_admin",
        "blocked",
        "telegram_username",
        "subscription_until",
        "package_left_sec",
    }
    assert found_name.json()[0]["telegram_username"] == username
    entries = await actions_of(admin)
    assert [entry.action for entry in entries] == ["users_searched"] * 4
    assert entries[1].target_label == str(telegram_id)
    assert entries[1].details == {"found": 1}


async def test_search_by_name_and_username_part_with_plan_marks(
    client: AsyncClient, make_user: MakeUser, admin: User
):
    marker = uuid.uuid4().hex[:8]
    named = await make_user()
    subscribed = await make_user(telegram_id=random.randint(10**9, 10**10))
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        stored = await session.get(User, named.id)
        stored.display_name = f"Мария Иванова {marker}"
        identity = await session.scalar(
            select(AuthIdentity).where(AuthIdentity.user_id == subscribed.id)
        )
        identity.data = {"username": f"masha_{marker}_ivanova"}
        session.add_all(
            [
                Subscription(
                    user_id=subscribed.id,
                    starts_at=now - timedelta(days=1),
                    ends_at=now + timedelta(days=10),
                ),
                Subscription(
                    user_id=subscribed.id,
                    starts_at=now + timedelta(days=10),
                    ends_at=now + timedelta(days=40),
                ),
                HourPackage(user_id=subscribed.id, seconds_total=7200, seconds_left=3600),
            ]
        )
        await session.commit()

    by_name = await client.get(
        "/api/v1/admin/users", params={"q": f"иванова {marker}".upper()}, headers=headers(admin)
    )
    by_part = await client.get(
        "/api/v1/admin/users", params={"q": marker.upper()}, headers=headers(admin)
    )

    assert [item["id"] for item in by_name.json()] == [str(named.id)]
    found = {item["id"]: item for item in by_part.json()}
    assert set(found) == {str(named.id), str(subscribed.id)}
    assert found[str(named.id)]["subscription_until"] is None
    assert found[str(named.id)]["package_left_sec"] == 0
    until = datetime.fromisoformat(found[str(subscribed.id)]["subscription_until"])
    assert abs(until - (now + timedelta(days=40))) < timedelta(seconds=1)
    assert found[str(subscribed.id)]["package_left_sec"] == 3600


async def test_make_admin_from_card(client: AsyncClient, make_user: MakeUser, admin: User):
    target = await make_user()
    blocked = await make_user()
    async with SessionLocal() as session:
        stored = await session.get(User, blocked.id)
        stored.blocked_at = datetime.now(UTC)
        await session.commit()

    granted = await client.post(f"/api/v1/admin/users/{target.id}/admin", headers=headers(admin))
    again = await client.post(f"/api/v1/admin/users/{target.id}/admin", headers=headers(admin))
    refused = await client.post(f"/api/v1/admin/users/{blocked.id}/admin", headers=headers(admin))
    refused_by_email = await client.post(
        "/api/v1/admin/admins", json={"identifier": blocked.email}, headers=headers(admin)
    )
    blank = await client.get("/api/v1/admin/users", params={"q": "   "}, headers=headers(admin))

    assert granted.status_code == 200
    assert granted.json()["is_admin"] is True
    assert again.status_code == 409
    assert refused.status_code == 409
    assert refused_by_email.status_code == 409
    assert blank.status_code == 422
    entries = await actions_of(admin)
    assert [(entry.action, entry.target_id) for entry in entries] == [
        ("admin_granted", str(target.id))
    ]


async def test_card_shows_account_and_logs_access(
    client: AsyncClient, make_user: MakeUser, admin: User
):
    user = await make_user(telegram_id=random.randint(10**9, 10**10))
    async with SessionLocal() as session:
        session.add_all(
            [
                Lecture(owner_id=user.id, title="Матанализ", source_type=SourceType.upload),
                Lecture(
                    owner_id=user.id,
                    title="Физика",
                    source_type=SourceType.link,
                    status=LectureStatus.failed,
                    duration_sec=600,
                ),
                Payment(
                    user_id=user.id,
                    kind=PaymentKind.package,
                    product_code="hours_5",
                    amount_kopecks=19900,
                    status=PaymentStatus.succeeded,
                    idempotence_key=uuid.uuid4().hex,
                    raw={"secret": "x"},
                ),
            ]
        )
        await session.commit()

    response = await client.get(f"/api/v1/admin/users/{user.id}", headers=headers(admin))

    assert response.status_code == 200
    card = response.json()
    assert card["email"] == user.email
    assert card["blocked_at"] is None
    assert [identity["provider"] for identity in card["identities"]] == ["telegram"]
    assert card["lectures"]["total"] == 2
    assert card["lectures"]["by_status"] == {"queued": 1, "failed": 1}
    assert "title" not in card["lectures"]["recent"][0]
    assert [payment["amount_kopecks"] for payment in card["payments"]] == [19900]
    assert "raw" not in card["payments"][0]
    assert "password_hash" not in card
    assert card["quota"]["subscription_until"] is None
    assert set(card["consents"]) >= {"terms_accepted_at", "personal_data_accepted_at"}
    [entry] = await actions_of(admin)
    assert (entry.action, entry.target_id) == ("user_viewed", str(user.id))
    missing = await client.get(f"/api/v1/admin/users/{uuid.uuid4()}", headers=headers(admin))
    assert missing.status_code == 404


async def test_grant_hours_adds_package_with_reason(
    client: AsyncClient, make_user: MakeUser, admin: User
):
    user = await make_user()

    response = await client.post(
        f"/api/v1/admin/users/{user.id}/hours",
        json={"hours": 3, "reason": "компенсация за сбой"},
        headers=headers(admin),
    )
    no_reason = await client.post(
        f"/api/v1/admin/users/{user.id}/hours", json={"hours": 3}, headers=headers(admin)
    )
    too_much = await client.post(
        f"/api/v1/admin/users/{user.id}/hours",
        json={"hours": 5000, "reason": "много"},
        headers=headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["quota"]["package_left_sec"] == 3 * 3600
    assert no_reason.status_code == 422
    assert too_much.status_code == 422
    [entry] = await actions_of(admin)
    assert entry.action == "hours_granted"
    assert entry.details == {"hours": 3, "reason": "компенсация за сбой"}
    quota = await client.get("/api/v1/billing/quota", headers=headers(user))
    assert quota.json()["package_left_sec"] == 3 * 3600


async def test_extend_subscription_from_now_and_after_current(
    client: AsyncClient, make_user: MakeUser, admin: User
):
    user = await make_user()
    before = datetime.now(UTC)

    first = await client.post(
        f"/api/v1/admin/users/{user.id}/subscription",
        json={"days": 10, "reason": "подарок"},
        headers=headers(admin),
    )
    second = await client.post(
        f"/api/v1/admin/users/{user.id}/subscription",
        json={"days": 5, "reason": "ещё подарок"},
        headers=headers(admin),
    )

    assert first.status_code == 200
    first_until = datetime.fromisoformat(first.json()["quota"]["subscription_until"])
    second_until = datetime.fromisoformat(second.json()["quota"]["subscription_until"])
    assert timedelta(days=10) <= first_until - before < timedelta(days=10, minutes=1)
    assert second_until - first_until == timedelta(days=5)
    assert first.json()["quota"]["weekly_limit_sec"] == get_settings().subscription_weekly_seconds
    async with SessionLocal() as session:
        periods = (
            await session.scalars(select(Subscription).where(Subscription.user_id == user.id))
        ).all()
    assert len(periods) == 2
    assert all(period.payment_id is None for period in periods)
    entries = await actions_of(admin)
    assert [entry.action for entry in entries] == ["subscription_extended"] * 2
    assert entries[0].details["days"] == 10


async def test_block_stops_requests_and_login_until_unblocked(
    client: AsyncClient, make_user: MakeUser, admin: User, reset_auth_rate_limits: None
):
    user = await with_password(await make_user())
    old_headers = headers(user)
    assert (await client.get("/api/v1/me", headers=old_headers)).status_code == 200

    blocked = await client.post(
        f"/api/v1/admin/users/{user.id}/block",
        json={"reason": "спам в поддержку"},
        headers=headers(admin),
    )

    assert blocked.status_code == 200
    assert blocked.json()["blocked_reason"] == "спам в поддержку"
    assert (await client.get("/api/v1/me", headers=old_headers)).status_code == 401
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert login.status_code == 423
    assert "заблокирован" in login.json()["detail"]
    again = await client.post(
        f"/api/v1/admin/users/{user.id}/block", json={"reason": "ещё раз"}, headers=headers(admin)
    )
    assert again.status_code == 409

    unblocked = await client.post(
        f"/api/v1/admin/users/{user.id}/unblock",
        json={"reason": "разобрались"},
        headers=headers(admin),
    )

    assert unblocked.status_code == 200
    assert unblocked.json()["blocked_at"] is None
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert login.status_code == 200
    fresh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get("/api/v1/me", headers=fresh)).status_code == 200
    entries = await actions_of(admin)
    assert [entry.action for entry in entries] == ["user_blocked", "user_unblocked"]
    assert entries[0].details == {"reason": "спам в поддержку"}


async def test_cannot_block_self_or_admin(client: AsyncClient, make_user: MakeUser, admin: User):
    other_admin = await make_user(is_admin=True)

    self_block = await client.post(
        f"/api/v1/admin/users/{admin.id}/block", json={"reason": "тест"}, headers=headers(admin)
    )
    admin_block = await client.post(
        f"/api/v1/admin/users/{other_admin.id}/block",
        json={"reason": "тест"},
        headers=headers(admin),
    )
    not_blocked = await client.post(
        f"/api/v1/admin/users/{other_admin.id}/unblock",
        json={"reason": "тест"},
        headers=headers(admin),
    )

    assert self_block.status_code == 409
    assert admin_block.status_code == 409
    assert not_blocked.status_code == 409
    assert await actions_of(admin) == []


def at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=MOSCOW)


@pytest.fixture
async def stats_data() -> AsyncIterator[tuple[date, date]]:
    first = date(2001, 3, 10)
    second = first + timedelta(days=1)
    async with SessionLocal() as session:
        early = User(display_name="Статистика", created_at=at(first, 1))
        late = User(display_name="Статистика", created_at=at(second, 23))
        outside = User(display_name="Статистика", created_at=at(first - timedelta(days=1), 23))
        session.add_all([early, late, outside])
        await session.flush()
        ready = Lecture(
            owner_id=early.id,
            title="Готовая",
            source_type=SourceType.upload,
            status=LectureStatus.ready,
            created_at=at(first, 10),
            updated_at=at(first, 11),
        )
        broken = Lecture(
            owner_id=late.id,
            title="Сломанная",
            source_type=SourceType.upload,
            status=LectureStatus.failed,
            created_at=at(first, 12),
            updated_at=at(second + timedelta(days=5), 2),
        )
        session.add_all([ready, broken])
        await session.flush()
        session.add_all(
            [
                ProcessingStep(
                    lecture_id=broken.id,
                    step=StepName.transcribe,
                    status=StepStatus.failed,
                    finished_at=at(second, 2),
                ),
                ProcessingStep(
                    lecture_id=broken.id,
                    step=StepName.summarize,
                    status=StepStatus.failed,
                    finished_at=at(second, 3),
                ),
                ProcessingStep(
                    lecture_id=ready.id,
                    step=StepName.transcribe,
                    status=StepStatus.done,
                    finished_at=at(first, 11),
                ),
                UsageEntry(
                    user_id=early.id,
                    lecture_id=ready.id,
                    source=UsageSource.weekly,
                    seconds=1800,
                    created_at=at(first, 10),
                ),
                UsageEntry(
                    user_id=early.id,
                    lecture_id=ready.id,
                    source=UsageSource.package,
                    seconds=600,
                    created_at=at(first, 10),
                ),
                UsageEntry(
                    user_id=early.id,
                    source=UsageSource.local_embeddings,
                    seconds=999,
                    created_at=at(first, 10),
                ),
            ]
        )
        payments = [
            Payment(
                user_id=early.id,
                kind=PaymentKind.subscription,
                product_code="subscription",
                amount_kopecks=amount,
                status=payment_status,
                idempotence_key=uuid.uuid4().hex,
                paid_at=paid_at,
            )
            for amount, payment_status, paid_at in (
                (29900, PaymentStatus.succeeded, at(second, 0)),
                (19900, PaymentStatus.succeeded, at(second, 5)),
                (34900, PaymentStatus.refunded, at(first, 5)),
                (50000, PaymentStatus.pending, None),
            )
        ]
        session.add_all(payments)
        await session.commit()
        user_ids = [early.id, late.id, outside.id]
        payment_ids = [payment.id for payment in payments]
    yield first, second
    async with SessionLocal() as session:
        await session.execute(delete(Payment).where(Payment.id.in_(payment_ids)))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()


async def test_stats_aggregate_by_moscow_days(stats_data: tuple[date, date]):
    first, second = stats_data

    async with SessionLocal() as session:
        stats = await collect_stats(session, first, second)

    assert stats.totals.model_dump() == {
        "new_users": 2,
        "lectures": 2,
        "processed_seconds": 2400,
        "failed_lectures": 1,
        "payments": 2,
        "revenue_kopecks": 49800,
        "refunds": 1,
        "refunded_kopecks": 34900,
    }
    by_day = {item.day: item for item in stats.days}
    assert list(by_day) == [first, second]
    assert (by_day[first].new_users, by_day[second].new_users) == (1, 1)
    assert (by_day[first].lectures, by_day[second].lectures) == (2, 0)
    assert (by_day[first].failed_lectures, by_day[second].failed_lectures) == (0, 1)
    assert by_day[second].revenue_kopecks == 49800


async def test_stats_endpoint_validates_and_caches(
    client: AsyncClient, admin: User, stats_data: tuple[date, date]
):
    first, second = stats_data
    redis = Redis.from_url(get_settings().redis_url)
    key = f"admin:stats:{first.isoformat()}:{second.isoformat()}"
    await redis.delete(key)
    params = {"date_from": first.isoformat(), "date_to": second.isoformat()}

    response = await client.get("/api/v1/admin/stats", params=params, headers=headers(admin))
    async with SessionLocal() as session:
        session.add(User(display_name="Поздний", created_at=at(first, 15)))
        await session.commit()
    cached = await client.get("/api/v1/admin/stats", params=params, headers=headers(admin))
    reversed_period = await client.get(
        "/api/v1/admin/stats",
        params={"date_from": second.isoformat(), "date_to": first.isoformat()},
        headers=headers(admin),
    )
    too_long = await client.get(
        "/api/v1/admin/stats",
        params={"date_from": "2000-01-01", "date_to": "2001-12-31"},
        headers=headers(admin),
    )
    default = await client.get("/api/v1/admin/stats", headers=headers(admin))

    assert response.status_code == 200
    assert response.json()["totals"]["new_users"] == 2
    assert cached.json() == response.json()
    assert reversed_period.status_code == 400
    assert too_long.status_code == 400
    assert len(default.json()["days"]) == 30
    await redis.delete(key)
    await redis.aclose()
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.display_name == "Поздний"))
        await session.commit()
