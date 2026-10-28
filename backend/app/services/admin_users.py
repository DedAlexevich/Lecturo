import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import Date, cast, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.models import (
    AdminAction,
    AuthIdentity,
    AuthProvider,
    HourPackage,
    Lecture,
    LectureStatus,
    Payment,
    PaymentStatus,
    Subscription,
    UsageEntry,
    User,
)
from app.pipeline.retention import extend_video_retention
from app.schemas.admin_users import (
    StatsDayOut,
    StatsOut,
    StatsTotalsOut,
    UserBriefOut,
    UserCardOut,
    UserConsentsOut,
    UserIdentityOut,
    UserLectureOut,
    UserLecturesOut,
    UserPaymentOut,
)
from app.schemas.billing import QuotaOut
from app.services.admin import USER_NOT_FOUND, grant_admin, record_action, user_label
from app.services.auth_tokens import bump_token_version
from app.services.quota import CHARGED_SOURCES, get_quota, subscription_until

MOSCOW = ZoneInfo("Europe/Moscow")
SEARCH_LIMIT = 20
CARD_PAYMENTS = 20
CARD_LECTURES = 10
STATS_CACHE_SECONDS = 300
STATS_MAX_DAYS = 366
CANNOT_BLOCK_SELF = "Нельзя заблокировать себя"
CANNOT_BLOCK_ADMIN = "Сначала снимите права администратора"
ALREADY_BLOCKED = "Аккаунт уже заблокирован"
NOT_BLOCKED = "Аккаунт не заблокирован"
BLOCKED_CANNOT_BE_ADMIN = "Сначала разблокируйте аккаунт"


def telegram_username(user: User) -> str | None:
    for identity in user.identities:
        if identity.provider == AuthProvider.telegram and identity.data:
            return identity.data.get("username")
    return None


async def search_users(
    session: AsyncSession, actor: User, query: str, now: datetime | None = None
) -> list[UserBriefOut]:
    now = now or datetime.now(UTC)
    value = query.strip()
    username = value.removeprefix("@")
    conditions = [
        User.email.icontains(value, autoescape=True),
        User.display_name.icontains(value, autoescape=True),
    ]
    telegram_match = [
        func.lower(AuthIdentity.data["username"].astext).contains(username.lower(), autoescape=True)
    ]
    if value.isdigit():
        telegram_match.append(AuthIdentity.provider_user_id == value)
    if username:
        conditions.append(
            User.id.in_(
                select(AuthIdentity.user_id).where(
                    AuthIdentity.provider == AuthProvider.telegram, or_(*telegram_match)
                )
            )
        )
    users = (
        await session.scalars(
            select(User)
            .where(or_(*conditions))
            .options(selectinload(User.identities))
            .order_by(User.created_at.desc(), User.id)
            .limit(SEARCH_LIMIT)
        )
    ).all()
    ids = [user.id for user in users]
    subscriptions = {user.id: await subscription_until(session, user.id, now) for user in users}
    packages = dict(
        (
            await session.execute(
                select(HourPackage.user_id, func.sum(HourPackage.seconds_left))
                .where(HourPackage.user_id.in_(ids))
                .group_by(HourPackage.user_id)
            )
        ).all()
    )
    record_action(
        session,
        actor,
        AdminAction.users_searched,
        "search",
        None,
        value,
        {"found": len(users)},
    )
    await session.commit()
    return [
        UserBriefOut(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            created_at=user.created_at,
            is_admin=user.is_admin,
            blocked=user.blocked_at is not None,
            telegram_username=telegram_username(user),
            subscription_until=subscriptions.get(user.id),
            package_left_sec=int(packages.get(user.id) or 0),
        )
        for user in users
    ]


async def get_user(session: AsyncSession, user_id: uuid.UUID, lock: bool = False) -> User:
    user = await session.get(
        User,
        user_id,
        options=[selectinload(User.identities)],
        with_for_update=lock,
        populate_existing=lock,
    )
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, USER_NOT_FOUND)
    return user


async def build_card(session: AsyncSession, user: User) -> UserCardOut:
    quota = await get_quota(session, user)
    payments = await session.scalars(
        select(Payment)
        .where(Payment.user_id == user.id)
        .order_by(Payment.created_at.desc(), Payment.id)
        .limit(CARD_PAYMENTS)
    )
    by_status = dict(
        (
            await session.execute(
                select(Lecture.status, func.count())
                .where(Lecture.owner_id == user.id)
                .group_by(Lecture.status)
            )
        ).all()
    )
    recent = await session.scalars(
        select(Lecture)
        .where(Lecture.owner_id == user.id)
        .order_by(Lecture.created_at.desc(), Lecture.id)
        .limit(CARD_LECTURES)
    )
    return UserCardOut(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        display_name=user.display_name,
        created_at=user.created_at,
        is_admin=user.is_admin,
        blocked_at=user.blocked_at,
        blocked_reason=user.blocked_reason,
        identities=[UserIdentityOut.model_validate(identity) for identity in user.identities],
        consents=UserConsentsOut.model_validate(user),
        quota=QuotaOut(
            weekly_limit_sec=quota.weekly_limit_sec,
            weekly_used_sec=quota.weekly_used_sec,
            package_left_sec=quota.package_left_sec,
            resets_at=quota.resets_at,
            subscription_until=quota.subscription_until,
        ),
        payments=[UserPaymentOut.model_validate(payment) for payment in payments],
        lectures=UserLecturesOut(
            total=sum(by_status.values()),
            by_status=by_status,
            recent=[UserLectureOut.model_validate(lecture) for lecture in recent],
        ),
    )


async def view_user(session: AsyncSession, actor: User, user_id: uuid.UUID) -> UserCardOut:
    user = await get_user(session, user_id)
    record_action(session, actor, AdminAction.user_viewed, "user", str(user.id), user_label(user))
    await session.commit()
    return await build_card(session, user)


async def finish_action(
    session: AsyncSession,
    actor: User,
    user: User,
    action: AdminAction,
    details: dict,
) -> UserCardOut:
    record_action(session, actor, action, "user", str(user.id), user_label(user), details)
    await session.commit()
    return await build_card(session, user)


async def make_admin(session: AsyncSession, actor: User, user_id: uuid.UUID) -> UserCardOut:
    user = await get_user(session, user_id)
    if user.blocked_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, BLOCKED_CANNOT_BE_ADMIN)
    await grant_admin(session, actor, user, "panel")
    await session.refresh(user, ["identities"])
    return await build_card(session, user)


async def grant_hours(
    session: AsyncSession, actor: User, user_id: uuid.UUID, hours: int, reason: str
) -> UserCardOut:
    user = await get_user(session, user_id, lock=True)
    seconds = hours * 3600
    session.add(HourPackage(user_id=user.id, seconds_total=seconds, seconds_left=seconds))
    return await finish_action(
        session, actor, user, AdminAction.hours_granted, {"hours": hours, "reason": reason}
    )


async def extend_subscription(
    session: AsyncSession,
    actor: User,
    user_id: uuid.UUID,
    days: int,
    reason: str,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> UserCardOut:
    now = now or datetime.now(UTC)
    settings = settings or get_settings()
    user = await get_user(session, user_id, lock=True)
    current_end = await session.scalar(
        select(func.max(Subscription.ends_at)).where(
            Subscription.user_id == user.id, Subscription.ends_at > now
        )
    )
    starts_at = current_end or now
    ends_at = starts_at + timedelta(days=days)
    session.add(Subscription(user_id=user.id, starts_at=starts_at, ends_at=ends_at))
    await extend_video_retention(session, user.id, now, settings)
    return await finish_action(
        session,
        actor,
        user,
        AdminAction.subscription_extended,
        {"days": days, "until": ends_at.isoformat(), "reason": reason},
    )


async def block_user(
    session: AsyncSession, actor: User, user_id: uuid.UUID, reason: str
) -> UserCardOut:
    if user_id == actor.id:
        raise HTTPException(status.HTTP_409_CONFLICT, CANNOT_BLOCK_SELF)
    user = await get_user(session, user_id, lock=True)
    if user.is_admin:
        raise HTTPException(status.HTTP_409_CONFLICT, CANNOT_BLOCK_ADMIN)
    if user.blocked_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, ALREADY_BLOCKED)
    user.blocked_at = datetime.now(UTC)
    user.blocked_reason = reason
    user.token_version = await bump_token_version(session, user.id)
    return await finish_action(session, actor, user, AdminAction.user_blocked, {"reason": reason})


async def unblock_user(
    session: AsyncSession, actor: User, user_id: uuid.UUID, reason: str
) -> UserCardOut:
    user = await get_user(session, user_id, lock=True)
    if user.blocked_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_BLOCKED)
    user.blocked_at = None
    user.blocked_reason = None
    return await finish_action(session, actor, user, AdminAction.user_unblocked, {"reason": reason})


def moscow_day(column):
    return cast(func.timezone(literal_column(f"'{MOSCOW.key}'"), column), Date)


def period_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    if date_to < date_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Начало периода позже конца")
    if (date_to - date_from).days >= STATS_MAX_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Период не длиннее {STATS_MAX_DAYS} дней")
    start = datetime.combine(date_from, time.min, MOSCOW)
    end = datetime.combine(date_to + timedelta(days=1), time.min, MOSCOW)
    return start, end


async def per_day(session: AsyncSession, column, value, *conditions) -> dict[date, int]:
    day = moscow_day(column)
    rows = await session.execute(select(day, value).where(*conditions).group_by(day))
    return {row[0]: int(row[1] or 0) for row in rows}


async def collect_stats(session: AsyncSession, date_from: date, date_to: date) -> StatsOut:
    start, end = period_bounds(date_from, date_to)

    def within(column):
        return (column >= start, column < end)

    new_users = await per_day(session, User.created_at, func.count(), *within(User.created_at))
    lectures = await per_day(session, Lecture.created_at, func.count(), *within(Lecture.created_at))
    processed = await per_day(
        session,
        UsageEntry.created_at,
        func.sum(UsageEntry.seconds),
        UsageEntry.source.in_(CHARGED_SOURCES),
        *within(UsageEntry.created_at),
    )
    failed = await per_day(
        session,
        Lecture.updated_at,
        func.count(),
        Lecture.status == LectureStatus.failed,
        *within(Lecture.updated_at),
    )
    paid = Payment.status == PaymentStatus.succeeded, *within(Payment.paid_at)
    payments = await per_day(session, Payment.paid_at, func.count(), *paid)
    revenue = await per_day(session, Payment.paid_at, func.sum(Payment.amount_kopecks), *paid)
    refunds, refunded = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Payment.amount_kopecks), 0)).where(
                Payment.status == PaymentStatus.refunded, *within(Payment.paid_at)
            )
        )
    ).one()
    days = [
        StatsDayOut(
            day=day,
            new_users=new_users.get(day, 0),
            lectures=lectures.get(day, 0),
            processed_seconds=processed.get(day, 0),
            failed_lectures=failed.get(day, 0),
            payments=payments.get(day, 0),
            revenue_kopecks=revenue.get(day, 0),
        )
        for day in (
            date_from + timedelta(days=offset) for offset in range((date_to - date_from).days + 1)
        )
    ]
    sums = {
        field: sum(getattr(item, field) for item in days)
        for field in StatsDayOut.model_fields
        if field != "day"
    }
    return StatsOut(
        date_from=date_from,
        date_to=date_to,
        generated_at=datetime.now(UTC),
        totals=StatsTotalsOut(**sums, refunds=refunds, refunded_kopecks=int(refunded)),
        days=days,
    )


async def cached_stats(
    session: AsyncSession, date_from: date, date_to: date, settings: Settings | None = None
) -> StatsOut:
    settings = settings or get_settings()
    redis = get_redis(settings.redis_url)
    key = f"admin:stats:{date_from.isoformat()}:{date_to.isoformat()}"
    cached = await redis.get(key)
    if cached is not None:
        return StatsOut.model_validate_json(cached)
    stats = await collect_stats(session, date_from, date_to)
    await redis.set(key, stats.model_dump_json(), ex=STATS_CACHE_SECONDS)
    return stats
