import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import (
    AdminAuditEntry,
    HourPackage,
    Payment,
    PaymentKind,
    PaymentStatus,
    PromoCode,
    PromoKind,
    PromoRedemption,
    Subscription,
    User,
)
from app.services import yookassa
from tests.test_admin import MakeUser, headers, make_user
from tests.test_yookassa import SETTINGS, FakeYooKassa, fake, product, user

__all__ = ["fake", "make_user", "user"]


@pytest.fixture
async def codes() -> AsyncIterator[list[str]]:
    created: list[str] = []
    yield created
    async with SessionLocal() as session:
        await session.execute(delete(PromoCode).where(PromoCode.code.in_(created)))
        await session.commit()


@pytest.fixture
async def admin(make_user: MakeUser) -> AsyncIterator[User]:
    user = await make_user(is_admin=True)
    yield user
    async with SessionLocal() as session:
        await session.execute(delete(AdminAuditEntry).where(AdminAuditEntry.actor_id == user.id))
        await session.commit()


@pytest.fixture(autouse=True)
async def reset_promo_limits() -> AsyncIterator[None]:
    yield
    redis = Redis.from_url(get_settings().redis_url)
    keys = [key async for key in redis.scan_iter("rate:promo:*")]
    if keys:
        await redis.delete(*keys)
    await redis.aclose()


async def add_code(codes: list[str], kind: PromoKind, **fields) -> PromoCode:
    code = f"T{uuid.uuid4().hex[:10].upper()}"
    async with SessionLocal() as session:
        promo = PromoCode(code=code, kind=kind, **fields)
        session.add(promo)
        await session.commit()
    codes.append(code)
    return promo


async def apply(client: AsyncClient, user: User, code: str):
    return await client.post("/api/v1/billing/promo", json={"code": code}, headers=headers(user))


async def test_hours_code_adds_package_once(client: AsyncClient, user: User, codes: list[str]):
    promo = await add_code(codes, PromoKind.hours, hours=3)

    first = await apply(client, user, f"  {promo.code.lower()} ")
    second = await apply(client, user, promo.code)

    assert first.status_code == 200
    assert first.json()["applied"] is True
    assert first.json()["hours"] == 3
    assert second.status_code == 422
    assert second.json()["detail"] == "Вы уже использовали этот промокод"
    async with SessionLocal() as session:
        packages = (
            await session.scalars(select(HourPackage).where(HourPackage.user_id == user.id))
        ).all()
    assert [(p.seconds_total, p.seconds_left, p.payment_id) for p in packages] == [
        (10800, 10800, None)
    ]


async def test_days_code_extends_after_current_subscription(
    client: AsyncClient, user: User, codes: list[str]
):
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        session.add(
            Subscription(
                user_id=user.id, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=5)
            )
        )
        await session.commit()
    promo = await add_code(codes, PromoKind.subscription_days, days=14)

    response = await apply(client, user, promo.code)

    assert response.status_code == 200
    quota = await client.get("/api/v1/billing/quota", headers=headers(user))
    until = datetime.fromisoformat(quota.json()["subscription_until"])
    assert abs(until - (now + timedelta(days=19))) < timedelta(minutes=1)


async def test_limits_expired_disabled_exhausted_and_unknown(
    client: AsyncClient, user: User, make_user: MakeUser, codes: list[str]
):
    now = datetime.now(UTC)
    expired = await add_code(
        codes, PromoKind.hours, hours=1, valid_until=now - timedelta(minutes=1)
    )
    disabled = await add_code(codes, PromoKind.hours, hours=1, disabled_at=now)
    single = await add_code(codes, PromoKind.hours, hours=1, max_redemptions=1)
    other = await make_user()

    taken = await apply(client, other, single.code)
    responses = [
        await apply(client, user, code)
        for code in (expired.code, disabled.code, single.code, "NOPE1234")
    ]

    assert taken.status_code == 200
    assert [r.status_code for r in responses] == [422] * 4
    assert [r.json()["detail"] for r in responses] == [
        "Срок действия промокода истёк",
        "Этот промокод больше не действует",
        "Промокод закончился: его уже использовали максимальное число раз",
        "Такого промокода нет. Проверьте, как он написан",
    ]


async def test_failed_attempts_are_limited(client: AsyncClient, user: User, codes: list[str]):
    limit = get_settings().promo_rate_limit
    for _ in range(limit):
        response = await apply(client, user, "WRONG000")
        assert response.status_code == 422
    promo = await add_code(codes, PromoKind.hours, hours=1)

    blocked = await apply(client, user, promo.code)

    assert blocked.status_code == 429


async def test_parallel_attempts_do_not_bypass_limit(client: AsyncClient, user: User):
    limit = get_settings().promo_rate_limit

    responses = await asyncio.gather(
        *(apply(client, user, f"WRONG{i:03d}") for i in range(limit + 5))
    )

    codes = sorted(response.status_code for response in responses)
    assert codes == [422] * limit + [429] * 5


async def test_discount_code_is_only_checked_without_payment(
    client: AsyncClient, user: User, codes: list[str]
):
    promo = await add_code(codes, PromoKind.discount, discount_percent=20)

    response = await apply(client, user, promo.code)

    assert response.status_code == 200
    assert response.json()["applied"] is False
    assert response.json()["discount_percent"] == 20
    async with SessionLocal() as session:
        used = await session.scalar(
            select(func.count())
            .select_from(PromoRedemption)
            .where(PromoRedemption.promo_id == promo.id)
        )
    assert used == 0


async def test_discount_goes_to_payment_and_receipt(user: User, codes: list[str]):
    promo = await add_code(codes, PromoKind.discount, discount_percent=25)
    settings = SETTINGS.model_copy(update={"yookassa_receipt": True})
    fake_kassa = FakeYooKassa()
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        payment = await yookassa.create_payment(
            session,
            fake_kassa.client(settings),
            db_user,
            product("hours_10"),
            "key-promo",
            "http://localhost/account",
            settings,
            promo_code=promo.code.lower(),
        )

    body = json.loads(fake_kassa.requests[0].content)
    assert (payment.amount_kopecks, payment.discount_kopecks) == (26175, 8725)
    assert body["amount"] == {"value": "261.75", "currency": "RUB"}
    [item] = body["receipt"]["items"]
    assert item["amount"] == {"value": "261.75", "currency": "RUB"}
    async with SessionLocal() as session:
        redemption = await session.scalar(
            select(PromoRedemption).where(PromoRedemption.promo_id == promo.id)
        )
    assert redemption.payment_id == payment.id


async def test_fixed_discount_keeps_minimal_price(
    client: AsyncClient, user: User, codes: list[str], fake: FakeYooKassa
):
    promo = await add_code(codes, PromoKind.discount, discount_kopecks=1_000_000)

    response = await client.post(
        "/api/v1/billing/payments",
        json={"product_code": "hours_5", "accept_offer": True, "promo_code": promo.code},
        headers={**headers(user), "Idempotence-Key": "key-fixed"},
    )

    assert response.status_code == 200
    assert response.json()["amount_kopecks"] == 100
    assert response.json()["discount_kopecks"] == 19800


async def test_canceled_payment_frees_discount_code(
    client: AsyncClient, user: User, codes: list[str], fake: FakeYooKassa
):
    promo = await add_code(codes, PromoKind.discount, discount_percent=10, max_redemptions=1)

    async def pay(key: str):
        return await client.post(
            "/api/v1/billing/payments",
            json={"product_code": "subscription", "accept_offer": True, "promo_code": promo.code},
            headers={**headers(user), "Idempotence-Key": key},
        )

    first = await pay("key-a")
    second = await pay("key-b")
    async with SessionLocal() as session:
        stored = await session.get(Payment, first.json()["id"])
        stored.status = PaymentStatus.canceled
        await session.commit()
    third = await pay("key-c")
    other_promo = await client.post(
        "/api/v1/billing/payments",
        json={"product_code": "subscription", "accept_offer": True},
        headers={**headers(user), "Idempotence-Key": "key-c"},
    )

    assert first.status_code == 200
    assert second.status_code == 422
    assert "неоплаченному платежу" in second.json()["detail"]
    assert third.status_code == 200
    assert third.json()["discount_kopecks"] == 2990
    assert other_promo.status_code == 409


async def test_stale_reservation_without_yookassa_payment_is_released(
    client: AsyncClient, user: User, codes: list[str], fake: FakeYooKassa
):
    promo = await add_code(codes, PromoKind.discount, discount_percent=10, max_redemptions=1)
    async with SessionLocal() as session:
        stuck = Payment(
            user_id=user.id,
            kind=PaymentKind.package,
            product_code="hours_5",
            amount_kopecks=17910,
            discount_kopecks=1990,
            idempotence_key="key-stuck",
            raw={},
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
        session.add(stuck)
        await session.flush()
        session.add(PromoRedemption(promo_id=promo.id, user_id=user.id, payment_id=stuck.id))
        await session.commit()

    response = await client.post(
        "/api/v1/billing/payments",
        json={"product_code": "hours_10", "accept_offer": True, "promo_code": promo.code},
        headers={**headers(user), "Idempotence-Key": "key-after-stuck"},
    )

    assert response.status_code == 200
    assert response.json()["discount_kopecks"] == 3490


async def test_non_discount_code_is_rejected_at_payment(
    client: AsyncClient, user: User, codes: list[str], fake: FakeYooKassa
):
    promo = await add_code(codes, PromoKind.hours, hours=2)

    response = await client.post(
        "/api/v1/billing/payments",
        json={"product_code": "hours_5", "accept_offer": True, "promo_code": promo.code},
        headers={**headers(user), "Idempotence-Key": "key-hours"},
    )

    assert response.status_code == 422
    assert fake.requests == []


async def test_admin_creates_lists_and_disables(
    client: AsyncClient, user: User, admin: User, codes: list[str]
):
    created = await client.post(
        "/api/v1/admin/promo-codes",
        json={"kind": "hours", "hours": 4, "max_redemptions": 10, "note": "Для группы"},
        headers=headers(admin),
    )
    code = created.json()["code"]
    codes.append(code)
    duplicate = await client.post(
        "/api/v1/admin/promo-codes",
        json={"code": code.lower(), "kind": "subscription_days", "days": 7},
        headers=headers(admin),
    )
    mismatch = await client.post(
        "/api/v1/admin/promo-codes",
        json={"kind": "discount", "hours": 4},
        headers=headers(admin),
    )
    applied = await apply(client, user, code)
    listed = await client.get("/api/v1/admin/promo-codes", headers=headers(admin))
    redemptions = await client.get(
        f"/api/v1/admin/promo-codes/{created.json()['id']}/redemptions", headers=headers(admin)
    )
    disabled = await client.post(
        f"/api/v1/admin/promo-codes/{created.json()['id']}/disable", headers=headers(admin)
    )
    again = await client.post(
        f"/api/v1/admin/promo-codes/{created.json()['id']}/disable", headers=headers(admin)
    )

    assert created.status_code == 201
    assert len(code) == 8
    assert duplicate.status_code == 409
    assert mismatch.status_code == 422
    assert applied.status_code == 200
    [row] = [item for item in listed.json() if item["code"] == code]
    assert row["redeemed"] == 1
    assert [item["user_id"] for item in redemptions.json()] == [str(user.id)]
    assert disabled.status_code == 200
    assert disabled.json()["disabled_at"] is not None
    assert disabled.json()["redeemed"] == 1
    assert again.status_code == 409
    async with SessionLocal() as session:
        entries = (
            await session.scalars(
                select(AdminAuditEntry)
                .where(AdminAuditEntry.actor_id == admin.id)
                .order_by(AdminAuditEntry.created_at)
            )
        ).all()
    assert [(entry.action, entry.target_label) for entry in entries] == [
        ("promo_created", code),
        ("promo_disabled", code),
    ]
    assert entries[0].details == {"kind": "hours", "hours": 4, "max_redemptions": 10}


async def test_regular_user_cannot_manage_codes(client: AsyncClient, user: User):
    listed = await client.get("/api/v1/admin/promo-codes", headers=headers(user))
    created = await client.post(
        "/api/v1/admin/promo-codes", json={"kind": "hours", "hours": 100}, headers=headers(user)
    )

    assert [listed.status_code, created.status_code] == [404, 404]
