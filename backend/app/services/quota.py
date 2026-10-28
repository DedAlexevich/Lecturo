import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import (
    HourPackage,
    Lecture,
    LectureStatus,
    PaymentKind,
    ProcessingStep,
    StepName,
    StepStatus,
    Subscription,
    UsageEntry,
    UsageSource,
    User,
)
from app.schemas.billing import ProductOut
from app.services.durations import format_duration

WEEK = timedelta(days=7)
CHARGED_SOURCES = (UsageSource.weekly, UsageSource.package)


class QuotaExceeded(Exception):
    pass


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
    periods = await session.execute(
        select(Subscription.starts_at, Subscription.ends_at)
        .where(Subscription.user_id == user_id, Subscription.ends_at > now)
        .order_by(Subscription.starts_at)
    )
    until = None
    for starts_at, ends_at in periods:
        if starts_at > (until or now):
            break
        until = max(until or ends_at, ends_at)
    return until


async def has_subscription(session: AsyncSession, user: User, now: datetime | None = None) -> bool:
    return await subscription_until(session, user.id, now or datetime.now(UTC)) is not None


async def video_retention_days(
    session: AsyncSession,
    user: User,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    if await has_subscription(session, user, now):
        return settings.subscription_video_retention_days
    return settings.free_video_retention_days


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
    if not duration_sec >= 0:
        raise ValueError("duration_sec must be a non-negative number")
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
    charged = (UsageEntry.lecture_id == lecture_id, UsageEntry.source.in_(CHARGED_SOURCES))
    user_id = await session.scalar(select(UsageEntry.user_id).where(*charged).limit(1))
    if user_id is None:
        return 0
    await session.get(User, user_id, with_for_update=True)
    entries = (await session.scalars(select(UsageEntry).where(*charged).with_for_update())).all()
    package_ids = [entry.package_id for entry in entries if entry.package_id is not None]
    packages = {
        package.id: package
        for package in await session.scalars(
            select(HourPackage)
            .where(HourPackage.id.in_(package_ids))
            .order_by(HourPackage.created_at, HourPackage.id)
            .with_for_update()
        )
    }
    for entry in entries:
        if entry.package_id is not None:
            packages[entry.package_id].seconds_left += entry.seconds
        await session.delete(entry)
    await session.flush()
    return sum(entry.seconds for entry in entries)


async def can_process(
    session: AsyncSession,
    user: User,
    seconds: float,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> bool:
    quota = await get_quota(session, user, now, settings)
    return math.ceil(seconds) <= quota.available_sec


async def refund_failed_lecture(session: AsyncSession, lecture_id: uuid.UUID) -> int:
    transcribed = await session.scalar(
        select(
            exists().where(
                ProcessingStep.lecture_id == lecture_id,
                ProcessingStep.step == StepName.transcribe,
                ProcessingStep.status == StepStatus.done,
            )
        )
    )
    if transcribed:
        return 0
    return await refund_lecture(session, lecture_id)


async def hold_if_over_quota(session: AsyncSession, user: User, lecture: Lecture) -> bool:
    if lecture.duration_sec is None or await can_process(session, user, lecture.duration_sec):
        return False
    lecture.status = LectureStatus.waiting_quota
    return True


async def list_waiting(session: AsyncSession, user_id: uuid.UUID) -> list[Lecture]:
    rows = await session.scalars(
        select(Lecture)
        .where(Lecture.owner_id == user_id, Lecture.status == LectureStatus.waiting_quota)
        .order_by(Lecture.created_at, Lecture.id)
    )
    return list(rows.all())


class QueuePlanError(Exception):
    pass


class LectureNotWaiting(QueuePlanError):
    pass


class PlanExceedsQuota(QueuePlanError):
    pass


async def plan_queue(
    session: AsyncSession,
    user: User,
    lecture_ids: list[uuid.UUID],
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[Lecture]:
    if len(set(lecture_ids)) != len(lecture_ids):
        raise QueuePlanError("Лекции в плане не должны повторяться")
    now = now or datetime.now(UTC)
    await session.get(User, user.id, with_for_update=True, populate_existing=True)
    rows = await session.scalars(
        select(Lecture)
        .where(Lecture.id.in_(lecture_ids), Lecture.owner_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    lectures = {lecture.id: lecture for lecture in rows}
    planned = [lectures.get(lecture_id) for lecture_id in lecture_ids]
    if any(lecture is None or lecture.status != LectureStatus.waiting_quota for lecture in planned):
        raise LectureNotWaiting("Часть лекций не ожидает лимита, обновите список")
    needed = sum(
        math.ceil(lecture.duration_sec) for lecture in planned if lecture.duration_sec is not None
    )
    if not await can_process(session, user, needed, now, settings):
        quota = await get_quota(session, user, now, settings)
        needed_text = format_duration(needed, round_up=True)
        left_text = format_duration(quota.available_sec, round_up=True)
        raise PlanExceedsQuota(
            f"Выбранные лекции длятся {needed_text}, "
            f"а осталось {left_text}. Уберите часть лекций из плана"
        )
    for lecture in planned:
        if lecture.duration_sec is not None:
            await charge_lecture(session, user.id, lecture.id, lecture.duration_sec, now, settings)
        lecture.status = LectureStatus.queued
    await session.flush()
    return planned


async def return_to_waiting(session: AsyncSession, lectures: list[Lecture]) -> None:
    for lecture in lectures:
        await refund_lecture(session, lecture.id)
        lecture.status = LectureStatus.waiting_quota
    await session.flush()


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
