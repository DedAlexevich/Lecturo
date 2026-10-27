import json
import logging
import secrets
import uuid
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.models import AuthIdentity, AuthProvider, User
from app.services.consents import record_signup_consents, require_telegram_signup_consents
from app.services.vk_auth import code_challenge

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 10 * 60
REQUEST_TIMEOUT_SECONDS = 10.0
YANDEX_PROFILE_FIELDS = ("login", "display_name", "real_name", "first_name", "last_name")
NOT_CONFIGURED = "Вход через Яндекс не настроен"
INVALID_STATE = "Сессия входа через Яндекс устарела, попробуйте ещё раз"
YANDEX_REJECTED = "Яндекс отклонил вход, попробуйте ещё раз"
YANDEX_UNAVAILABLE = "Яндекс временно недоступен, попробуйте позже"


class YandexClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def request(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=REQUEST_TIMEOUT_SECONDS
            ) as client:
                response = await client.request(method, url, data=data, headers=headers)
        except httpx.HTTPError:
            logger.exception("Запрос к Яндексу не выполнен")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, YANDEX_UNAVAILABLE) from None
        if response.status_code >= 500:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, YANDEX_UNAVAILABLE)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code != 200 or not isinstance(payload, dict) or "error" in payload:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, YANDEX_REJECTED)
        return payload

    async def exchange_code(self, code: str, verifier: str) -> str:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": self.settings.yandex_oauth_client_id,
        }
        if self.settings.yandex_oauth_client_secret:
            form["client_secret"] = self.settings.yandex_oauth_client_secret
        payload = await self.request("POST", self.settings.yandex_oauth_token_url, data=form)
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, YANDEX_REJECTED)
        return access_token

    async def fetch_profile(self, access_token: str) -> tuple[str, dict]:
        payload = await self.request(
            "GET",
            f"{self.settings.yandex_oauth_user_info_url}?format=json",
            headers={"Authorization": f"OAuth {access_token}"},
        )
        yandex_id = payload.get("id")
        if (
            not isinstance(yandex_id, str | int)
            or isinstance(yandex_id, bool)
            or not str(yandex_id)
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, YANDEX_REJECTED)
        profile = {
            key: payload[key] for key in YANDEX_PROFILE_FIELDS if isinstance(payload.get(key), str)
        }
        return str(yandex_id), profile


def get_yandex_client() -> YandexClient:
    return YandexClient(get_settings())


YandexClientDep = Annotated[YandexClient, Depends(get_yandex_client)]


def require_yandex_enabled(settings: Settings) -> None:
    if not settings.yandex_oauth_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED)


def state_key(state: str) -> str:
    return f"yandex:state:{state}"


async def start_flow(
    settings: Settings,
    user_id: uuid.UUID | None = None,
    accept_terms: bool = False,
    accept_personal_data: bool = False,
) -> tuple[str, str]:
    require_yandex_enabled(settings)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    record = {
        "verifier": verifier,
        "nonce": nonce,
        "user_id": str(user_id) if user_id else None,
        "accept_terms": accept_terms,
        "accept_personal_data": accept_personal_data,
    }
    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.set(state_key(state), json.dumps(record), ex=STATE_TTL_SECONDS)
    except (OSError, RedisError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, YANDEX_UNAVAILABLE) from None
    finally:
        await redis.aclose()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.yandex_oauth_client_id,
            "redirect_uri": settings.yandex_oauth_redirect_uri,
            "state": state,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{settings.yandex_oauth_authorize_url}?{query}", nonce


async def take_flow(settings: Settings, state: str, nonce: str, user_id: uuid.UUID | None) -> dict:
    redis = Redis.from_url(settings.redis_url)
    try:
        raw = await redis.get(state_key(state))
        if raw is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID_STATE)
        record = json.loads(raw)
        if not secrets.compare_digest(record["nonce"], nonce) or record["user_id"] != (
            str(user_id) if user_id else None
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID_STATE)
        if await redis.getdel(state_key(state)) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID_STATE)
    except (OSError, RedisError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, YANDEX_UNAVAILABLE) from None
    finally:
        await redis.aclose()
    return record


async def complete_flow(
    settings: Settings,
    client: YandexClient,
    code: str,
    state: str,
    nonce: str,
    user_id: uuid.UUID | None = None,
) -> tuple[str, dict, dict]:
    require_yandex_enabled(settings)
    record = await take_flow(settings, state, nonce, user_id)
    access_token = await client.exchange_code(code, record["verifier"])
    yandex_id, profile = await client.fetch_profile(access_token)
    return yandex_id, profile, record


async def find_yandex_identity(session: AsyncSession, yandex_id: str) -> AuthIdentity | None:
    return await session.scalar(
        select(AuthIdentity)
        .where(
            AuthIdentity.provider == AuthProvider.yandex,
            AuthIdentity.provider_user_id == yandex_id,
        )
        .options(selectinload(AuthIdentity.user))
    )


def display_name_of(profile: dict) -> str:
    return (
        profile.get("real_name")
        or " ".join(part for part in (profile.get("first_name"), profile.get("last_name")) if part)
        or profile.get("display_name")
        or profile.get("login")
        or "Пользователь Яндекса"
    )[:120]


async def get_or_create_yandex_user(
    session: AsyncSession,
    yandex_id: str,
    profile: dict,
    accept_terms: bool = False,
    accept_personal_data: bool = False,
) -> User:
    identity = await find_yandex_identity(session, yandex_id)
    if identity is None:
        require_telegram_signup_consents(accept_terms, accept_personal_data)
        user = User(display_name=display_name_of(profile))
        record_signup_consents(user)
        user.identities.append(
            AuthIdentity(provider=AuthProvider.yandex, provider_user_id=yandex_id, data=profile)
        )
        session.add(user)
        try:
            await session.commit()
            return user
        except IntegrityError:
            await session.rollback()
            identity = await find_yandex_identity(session, yandex_id)
            if identity is None:
                raise
    identity.data = profile
    await session.commit()
    return identity.user
