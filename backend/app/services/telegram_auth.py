import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import AuthIdentity, AuthProvider, User
from app.schemas.user import TelegramLoginIn
from app.services.consents import record_signup_consents, require_telegram_signup_consents

AUTH_MAX_AGE_SECONDS = 24 * 60 * 60
WEBAPP_AUTH_MAX_AGE_SECONDS = 60 * 60
CLOCK_SKEW_SECONDS = 5 * 60
TELEGRAM_PROFILE_FIELDS = {"first_name", "last_name", "username", "photo_url"}


def bot_token() -> str:
    token = get_settings().telegram_bot_token
    if not token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Вход через Telegram не настроен")
    return token


def verify_login_widget(data: TelegramLoginIn) -> None:
    fields = data.model_dump(
        include=set(TelegramLoginIn.model_fields) - {"hash"}, exclude_none=True
    )
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hashlib.sha256(bot_token().encode()).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, data.hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверная подпись Telegram")
    age = time.time() - data.auth_date
    if age > AUTH_MAX_AGE_SECONDS or age < -CLOCK_SKEW_SECONDS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Данные входа Telegram устарели")


def verify_webapp_init_data(init_data: str) -> dict:
    secret = hmac.new(b"WebAppData", bot_token().encode(), hashlib.sha256).digest()
    pairs = parse_qsl(init_data, keep_blank_values=True)
    fields = dict(pairs)
    received_hash = fields.pop("hash", None)
    if not received_hash or len(fields) + 1 != len(pairs):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверная подпись Telegram")
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверная подпись Telegram")
    try:
        age = time.time() - int(fields["auth_date"])
        telegram_user = json.loads(fields["user"])
        telegram_user["id"] = int(telegram_user["id"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Неполные данные входа Telegram"
        ) from None
    if age > WEBAPP_AUTH_MAX_AGE_SECONDS or age < -CLOCK_SKEW_SECONDS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Данные входа Telegram устарели")
    return telegram_user


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
    session: AsyncSession,
    telegram_id: int,
    profile: dict,
    accept_terms: bool = False,
    accept_personal_data: bool = False,
) -> User:
    identity = await find_identity(session, telegram_id)
    if identity is None:
        require_telegram_signup_consents(accept_terms, accept_personal_data)
        display_name = " ".join(
            part for part in (profile.get("first_name"), profile.get("last_name")) if part
        )
        user = User(display_name=display_name[:120], telegram_chat_id=telegram_id)
        record_signup_consents(user)
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
