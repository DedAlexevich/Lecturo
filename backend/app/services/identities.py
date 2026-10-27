import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuthIdentity,
    AuthProvider,
    Course,
    HourPackage,
    Lecture,
    Payment,
    ShareLink,
    Subscription,
    UsageEntry,
    User,
)
from app.schemas.user import EmailIdentityIn, IdentityOut, TelegramNotifications, UserOut
from app.services.auth import hash_password, normalize_email
from app.services.auth_tokens import bump_token_version, revoke_unused_tokens
from app.services.consents import ai_transfer_given, current_ai_transfer_revision

TELEGRAM_TAKEN = "Этот Telegram уже привязан к другому аккаунту"
VK_TAKEN = "Этот VK уже привязан к другому аккаунту"
YANDEX_TAKEN = "Этот Яндекс уже привязан к другому аккаунту"
EMAIL_TAKEN = "Этот email уже используется"
EMAIL_TAKEN_FOR_TELEGRAM = (
    "Этот email уже используется другим аккаунтом. Выйдите, войдите по этой почте "
    "и привяжите Telegram там"
)
TELEGRAM_ACCOUNT_NOT_EMPTY = (
    "Этот Telegram привязан к другому аккаунту, в котором уже есть данные. "
    "Выйдите и войдите в тот аккаунт через Telegram"
)


async def user_out(session: AsyncSession, user: User) -> UserOut:
    await session.refresh(user, ["identities"])
    return UserOut(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        display_name=user.display_name,
        ai_transfer_accepted_at=user.ai_transfer_accepted_at
        if ai_transfer_given(user.ai_transfer_accepted_at, user.ai_transfer_revision)
        else None,
        identities=[IdentityOut.model_validate(identity) for identity in user.identities],
        telegram_notifications=telegram_notifications(user.identities),
    )


def telegram_notifications(user_identities: list[AuthIdentity]) -> TelegramNotifications:
    telegram = next(
        (item for item in user_identities if item.provider == AuthProvider.telegram), None
    )
    if telegram is None:
        return TelegramNotifications.not_linked
    started, blocked = telegram.bot_started_at, telegram.bot_blocked_at
    if blocked is not None and (started is None or blocked > started):
        return TelegramNotifications.blocked
    if started is not None:
        return TelegramNotifications.ready
    return TelegramNotifications.start_required


async def find_identity(
    session: AsyncSession, provider: AuthProvider, provider_user_id: str
) -> AuthIdentity | None:
    return await session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == provider,
            AuthIdentity.provider_user_id == provider_user_id,
        )
    )


async def user_identity(
    session: AsyncSession, user: User, provider: AuthProvider
) -> AuthIdentity | None:
    return await session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.user_id == user.id, AuthIdentity.provider == provider
        )
    )


async def has_user_data(session: AsyncSession, user_id: uuid.UUID) -> bool:
    for model, column in (
        (Lecture, Lecture.owner_id),
        (Course, Course.owner_id),
        (ShareLink, ShareLink.owner_id),
        (Payment, Payment.user_id),
        (Subscription, Subscription.user_id),
        (HourPackage, HourPackage.user_id),
        (UsageEntry, UsageEntry.user_id),
    ):
        if await session.scalar(select(model.id).where(column == user_id).limit(1)) is not None:
            return True
    return False


async def absorb_empty_telegram_owner(
    session: AsyncSession, existing: AuthIdentity, telegram_id: int
) -> None:
    owner = await session.scalar(select(User).where(User.id == existing.user_id).with_for_update())
    if owner is None:
        return
    await session.refresh(owner, ["identities"])
    only_telegram = [
        item
        for item in owner.identities
        if item.provider == AuthProvider.telegram and item.provider_user_id == str(telegram_id)
    ]
    if (
        owner.email is not None
        or len(owner.identities) != len(only_telegram)
        or await has_user_data(session, owner.id)
    ):
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, TELEGRAM_ACCOUNT_NOT_EMPTY)
    session.expunge(existing)
    await session.execute(delete(User).where(User.id == owner.id))
    session.expunge(owner)


async def link_telegram(session: AsyncSession, user: User, telegram_id: int, profile: dict) -> None:
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    own = await user_identity(session, user, AuthProvider.telegram)
    if own is not None and own.provider_user_id != str(telegram_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "К аккаунту уже привязан другой Telegram")
    existing = await find_identity(session, AuthProvider.telegram, str(telegram_id))
    if existing is not None and existing.user_id != user.id:
        await absorb_empty_telegram_owner(session, existing, telegram_id)
    if own is None:
        session.add(
            AuthIdentity(
                user_id=user.id,
                provider=AuthProvider.telegram,
                provider_user_id=str(telegram_id),
                data=profile,
            )
        )
    else:
        own.data = profile
    user.telegram_chat_id = telegram_id
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, TELEGRAM_TAKEN) from None


async def link_vk(session: AsyncSession, user: User, vk_id: str, profile: dict) -> None:
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    existing = await find_identity(session, AuthProvider.vk, vk_id)
    if existing is not None and existing.user_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, VK_TAKEN)
    own = await user_identity(session, user, AuthProvider.vk)
    if own is not None and own.provider_user_id != vk_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "К аккаунту уже привязан другой VK")
    if own is None:
        session.add(
            AuthIdentity(
                user_id=user.id, provider=AuthProvider.vk, provider_user_id=vk_id, data=profile
            )
        )
    else:
        own.data = profile
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, VK_TAKEN) from None


async def link_yandex(session: AsyncSession, user: User, yandex_id: str, profile: dict) -> None:
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    existing = await find_identity(session, AuthProvider.yandex, yandex_id)
    if existing is not None and existing.user_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, YANDEX_TAKEN)
    own = await user_identity(session, user, AuthProvider.yandex)
    if own is not None and own.provider_user_id != yandex_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "К аккаунту уже привязан другой Яндекс")
    if own is None:
        session.add(
            AuthIdentity(
                user_id=user.id,
                provider=AuthProvider.yandex,
                provider_user_id=yandex_id,
                data=profile,
            )
        )
    else:
        own.data = profile
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, YANDEX_TAKEN) from None


async def email_taken_message(session: AsyncSession, user: User) -> str:
    if await user_identity(session, user, AuthProvider.telegram) is not None:
        return EMAIL_TAKEN_FOR_TELEGRAM
    return EMAIL_TAKEN


async def link_email(session: AsyncSession, user: User, body: EmailIdentityIn) -> None:
    if user.email is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "К аккаунту уже привязан email")
    email = normalize_email(body.email)
    taken = await email_taken_message(session, user)
    if await session.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, taken)
    user.email = email
    user.email_verified_at = None
    user.password_hash = hash_password(body.password)
    session.add(AuthIdentity(user_id=user.id, provider=AuthProvider.email, provider_user_id=email))
    await revoke_unused_tokens(session, user.id)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, taken) from None


async def unlink_identity(session: AsyncSession, user: User, provider: AuthProvider) -> int:
    await session.refresh(user, ["identities"])
    identity = next((item for item in user.identities if item.provider == provider), None)
    if identity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Этот способ входа не привязан")
    if len(user.identities) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя отвязать последний способ входа")
    if provider == AuthProvider.email:
        user.email = None
        user.email_verified_at = None
        user.password_hash = None
        await revoke_unused_tokens(session, user.id)
    elif provider == AuthProvider.telegram:
        user.telegram_chat_id = None
    await session.delete(identity)
    version = await bump_token_version(session, user.id)
    await session.commit()
    return version


async def accept_ai_transfer(session: AsyncSession, user: User) -> None:
    if not ai_transfer_given(user.ai_transfer_accepted_at, user.ai_transfer_revision):
        user.ai_transfer_accepted_at = datetime.now(UTC)
        user.ai_transfer_revision = current_ai_transfer_revision()
        await session.commit()


async def revoke_ai_transfer(session: AsyncSession, user: User) -> None:
    user.ai_transfer_accepted_at = None
    user.ai_transfer_revision = None
    await session.commit()
