from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthIdentity, AuthProvider, User
from app.schemas.user import EmailIdentityIn, IdentityOut, UserOut
from app.services.auth import hash_password, normalize_email

TELEGRAM_TAKEN = "Этот Telegram уже привязан к другому аккаунту"
EMAIL_TAKEN = "Этот email уже используется"


async def user_out(session: AsyncSession, user: User) -> UserOut:
    await session.refresh(user, ["identities"])
    return UserOut(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        display_name=user.display_name,
        ai_transfer_accepted_at=user.ai_transfer_accepted_at,
        identities=[IdentityOut.model_validate(identity) for identity in user.identities],
    )


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


async def link_telegram(session: AsyncSession, user: User, telegram_id: int, profile: dict) -> None:
    existing = await find_identity(session, AuthProvider.telegram, str(telegram_id))
    if existing is not None and existing.user_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, TELEGRAM_TAKEN)
    own = await user_identity(session, user, AuthProvider.telegram)
    if own is not None and own.provider_user_id != str(telegram_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "К аккаунту уже привязан другой Telegram")
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


async def link_email(session: AsyncSession, user: User, body: EmailIdentityIn) -> None:
    if user.email is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "К аккаунту уже привязан email")
    email = normalize_email(body.email)
    if await session.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, EMAIL_TAKEN)
    user.email = email
    user.email_verified_at = None
    user.password_hash = hash_password(body.password)
    session.add(AuthIdentity(user_id=user.id, provider=AuthProvider.email, provider_user_id=email))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, EMAIL_TAKEN) from None


async def unlink_identity(session: AsyncSession, user: User, provider: AuthProvider) -> None:
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
    elif provider == AuthProvider.telegram:
        user.telegram_chat_id = None
    await session.delete(identity)
    await session.commit()


async def accept_ai_transfer(session: AsyncSession, user: User) -> None:
    if user.ai_transfer_accepted_at is None:
        user.ai_transfer_accepted_at = datetime.now(UTC)
        await session.commit()
