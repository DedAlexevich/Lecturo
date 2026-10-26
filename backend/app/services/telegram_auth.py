import hashlib
import hmac
import time

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import AuthIdentity, AuthProvider, User
from app.schemas.user import TelegramLoginIn

AUTH_MAX_AGE_SECONDS = 24 * 60 * 60


def bot_token() -> str:
    token = get_settings().telegram_bot_token
    if not token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Вход через Telegram не настроен")
    return token


def verify_login_widget(data: TelegramLoginIn) -> None:
    fields = data.model_dump(exclude={"hash"}, exclude_none=True)
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hashlib.sha256(bot_token().encode()).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, data.hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверная подпись Telegram")
    if time.time() - data.auth_date > AUTH_MAX_AGE_SECONDS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Данные входа Telegram устарели")


async def find_identity(session: AsyncSession, telegram_id: int) -> AuthIdentity | None:
    return await session.scalar(
        select(AuthIdentity)
        .where(
            AuthIdentity.provider == AuthProvider.telegram,
            AuthIdentity.provider_user_id == str(telegram_id),
        )
        .options(selectinload(AuthIdentity.user))
    )


async def get_or_create_telegram_user(
    session: AsyncSession, telegram_id: int, profile: dict
) -> User:
    identity = await find_identity(session, telegram_id)
    if identity is None:
        display_name = " ".join(
            part for part in (profile.get("first_name"), profile.get("last_name")) if part
        )
        user = User(display_name=display_name[:120], telegram_chat_id=telegram_id)
        user.identities.append(
            AuthIdentity(
                provider=AuthProvider.telegram, provider_user_id=str(telegram_id), data=profile
            )
        )
        session.add(user)
        try:
            await session.commit()
            return user
        except IntegrityError:
            await session.rollback()
            identity = await find_identity(session, telegram_id)
            if identity is None:
                raise
    identity.data = profile
    identity.user.telegram_chat_id = telegram_id
    await session.commit()
    return identity.user
