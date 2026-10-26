import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import HourPackage, PaymentKind, Subscription, UsageEntry, UsageSource, User
from app.schemas.billing import ProductOut

WEEK = timedelta(days=7)
CHARGED_SOURCES = (UsageSource.weekly, UsageSource.package)


@dataclass
class Quota:
    weekly_limit_sec: int
    weekly_used_sec: int
    package_left_sec: int
    resets_at: datetime
    subscription_until: datetime | None

    @property
    def weekly_left_sec(self) -> int:
        return max(self.weekly_limit_sec - self.weekly_used_sec, 0)

    @property
    def available_sec(self) -> int:
        return self.weekly_left_sec + self.package_left_sec


def current_week_start(week_start: datetime, now: datetime) -> datetime:
    if now < week_start + WEEK:
        return week_start
    return week_start + (now - week_start) // WEEK * WEEK


async def subscription_until(
    session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> datetime | None:
    return await session.scalar(
        select(func.max(Subscription.ends_at)).where(
            Subscription.user_id == user_id,
            Subscription.starts_at <= now,
            Subscription.ends_at > now,
        )
    )


async def get_quota(
    session: AsyncSession,
    user: User,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> Quota:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    user.quota_week_start = current_week_start(user.quota_week_start, now)
    until = await subscription_until(session, user.id, now)
    weekly_used = await session.scalar(
        select(func.coalesce(func.sum(UsageEntry.seconds), 0)).where(
            UsageEntry.user_id == user.id,
            UsageEntry.source == UsageSource.weekly,
            UsageEntry.created_at >= user.quota_week_start,
        )
    )
    package_left = await session.scalar(
        select(func.coalesce(func.sum(HourPackage.seconds_left), 0)).where(
            HourPackage.user_id == user.id
        )
    )
    return Quota(
        weekly_limit_sec=(
            settings.subscription_weekly_seconds if until else settings.free_weekly_seconds
        ),
        weekly_used_sec=weekly_used,
        package_left_sec=package_left,
        resets_at=user.quota_week_start + WEEK,
        subscription_until=until,
    )


async def is_charged(session: AsyncSession, lecture_id: uuid.UUID) -> bool:
    return await session.scalar(
        select(
            exists().where(
                UsageEntry.lecture_id == lecture_id, UsageEntry.source.in_(CHARGED_SOURCES)
            )
        )
    )


async def charge_lecture(
    session: AsyncSession,
    user_id: uuid.UUID,
    lecture_id: uuid.UUID,
    duration_sec: float,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    user = await session.get(User, user_id, with_for_update=True, populate_existing=True)
    if await is_charged(session, lecture_id):
        return True
    seconds = math.ceil(duration_sec)
    quota = await get_quota(session, user, now, settings)
    if seconds > quota.available_sec:
        return False

    from_week = min(seconds, quota.weekly_left_sec)
    if from_week:
        session.add(
            UsageEntry(
                user_id=user_id,
                lecture_id=lecture_id,
                source=UsageSource.weekly,
                seconds=from_week,
                created_at=now,
            )
        )
    rest = seconds - from_week
    packages = await session.scalars(
        select(HourPackage)
        .where(HourPackage.user_id == user_id, HourPackage.seconds_left > 0)
        .order_by(HourPackage.created_at, HourPackage.id)
        .with_for_update()
    )
    for package in packages:
        if not rest:
            break
        taken = min(rest, package.seconds_left)
        package.seconds_left -= taken
        rest -= taken
        session.add(
            UsageEntry(
                user_id=user_id,
                lecture_id=lecture_id,
                source=UsageSource.package,
                package_id=package.id,
                seconds=taken,
                created_at=now,
            )
        )
    await session.flush()
    return True


async def refund_lecture(session: AsyncSession, lecture_id: uuid.UUID) -> int:
    entries = (
        await session.scalars(
            select(UsageEntry)
            .where(UsageEntry.lecture_id == lecture_id, UsageEntry.source.in_(CHARGED_SOURCES))
            .with_for_update()
        )
    ).all()
    for entry in entries:
        if entry.package_id is not None:
            package = await session.get(HourPackage, entry.package_id, with_for_update=True)
            package.seconds_left += entry.seconds
        await session.delete(entry)
    await session.flush()
    return sum(entry.seconds for entry in entries)


def list_products(settings: Settings | None = None) -> list[ProductOut]:
    settings = settings or get_settings()
    subscription = ProductOut(
        code="subscription",
        kind=PaymentKind.subscription,
        title=f"Подписка на {settings.subscription_days} дней",
        price_rub=settings.subscription_price_rub,
        seconds=None,
    )
    packages = [
        ProductOut(
            code=f"hours_{hours}",
            kind=PaymentKind.package,
            title=f"Пакет {hours} ч",
            price_rub=price,
            seconds=hours * 3600,
        )
        for hours, price in sorted(settings.hour_packages.items())
    ]
    return [subscription, *packages]
