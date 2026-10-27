import base64
import hashlib
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

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 10 * 60
REQUEST_TIMEOUT_SECONDS = 10.0
VK_PROFILE_FIELDS = ("first_name", "last_name", "avatar")
NOT_CONFIGURED = "Вход через VK не настроен"
INVALID_STATE = "Сессия входа через VK устарела, попробуйте ещё раз"
VK_REJECTED = "VK отклонил вход, попробуйте ещё раз"
VK_UNAVAILABLE = "VK временно недоступен, попробуйте позже"


class VkClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def post(self, url: str, data: dict[str, str]) -> dict:
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=REQUEST_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(url, data=data)
        except httpx.HTTPError:
            logger.exception("Запрос к VK ID не выполнен")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, VK_UNAVAILABLE) from None
        if response.status_code >= 500:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, VK_UNAVAILABLE)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code != 200 or not isinstance(payload, dict) or "error" in payload:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, VK_REJECTED)
        return payload

    async def exchange_code(self, code: str, verifier: str, device_id: str, state: str) -> str:
        payload = await self.post(
            self.settings.vk_token_url,
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "client_id": self.settings.vk_client_id,
                "device_id": device_id,
                "redirect_uri": self.settings.vk_redirect_uri,
                "state": state,
            },
        )
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, VK_REJECTED)
        return access_token

    async def fetch_profile(self, access_token: str) -> tuple[str, dict]:
        payload = await self.post(
            self.settings.vk_user_info_url,
            {"client_id": self.settings.vk_client_id, "access_token": access_token},
        )
        user = payload.get("user")
        vk_id = user.get("user_id") if isinstance(user, dict) else None
        if not isinstance(vk_id, str | int) or isinstance(vk_id, bool) or not str(vk_id):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, VK_REJECTED)
        profile = {key: user[key] for key in VK_PROFILE_FIELDS if isinstance(user.get(key), str)}
        return str(vk_id), profile


def get_vk_client() -> VkClient:
    return VkClient(get_settings())


VkClientDep = Annotated[VkClient, Depends(get_vk_client)]


def require_vk_enabled(settings: Settings) -> None:
    if not settings.vk_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def state_key(state: str) -> str:
    return f"vk:state:{state}"


async def start_flow(
    settings: Settings,
    user_id: uuid.UUID | None = None,
    accept_terms: bool = False,
    accept_personal_data: bool = False,
) -> tuple[str, str]:
    require_vk_enabled(settings)
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
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, VK_UNAVAILABLE) from None
    finally:
        await redis.aclose()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.vk_client_id,
            "redirect_uri": settings.vk_redirect_uri,
            "state": state,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{settings.vk_authorize_url}?{query}", nonce


async def take_flow(settings: Settings, state: str, nonce: str, user_id: uuid.UUID | None) -> dict:
    redis = Redis.from_url(settings.redis_url)
    try:
        raw = await redis.getdel(state_key(state))
    except (OSError, RedisError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, VK_UNAVAILABLE) from None
    finally:
        await redis.aclose()
    if raw is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID_STATE)
    record = json.loads(raw)
    if not secrets.compare_digest(record["nonce"], nonce) or record["user_id"] != (
        str(user_id) if user_id else None
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID_STATE)
    return record


async def complete_flow(
    settings: Settings,
    client: VkClient,
    code: str,
    state: str,
    device_id: str,
    nonce: str,
    user_id: uuid.UUID | None = None,
) -> tuple[str, dict, dict]:
    require_vk_enabled(settings)
    record = await take_flow(settings, state, nonce, user_id)
    access_token = await client.exchange_code(code, record["verifier"], device_id, state)
    vk_id, profile = await client.fetch_profile(access_token)
    return vk_id, profile, record


async def find_vk_identity(session: AsyncSession, vk_id: str) -> AuthIdentity | None:
    return await session.scalar(
        select(AuthIdentity)
        .where(AuthIdentity.provider == AuthProvider.vk, AuthIdentity.provider_user_id == vk_id)
        .options(selectinload(AuthIdentity.user))
    )


async def get_or_create_vk_user(
    session: AsyncSession,
    vk_id: str,
    profile: dict,
    accept_terms: bool = False,
    accept_personal_data: bool = False,
) -> User:
    identity = await find_vk_identity(session, vk_id)
    if identity is None:
        require_telegram_signup_consents(accept_terms, accept_personal_data)
        display_name = " ".join(
            part for part in (profile.get("first_name"), profile.get("last_name")) if part
        )
        user = User(display_name=(display_name or "Пользователь VK")[:120])
        record_signup_consents(user)
        user.identities.append(
            AuthIdentity(provider=AuthProvider.vk, provider_user_id=vk_id, data=profile)
        )
        session.add(user)
        try:
            await session.commit()
            return user
        except IntegrityError:
            await session.rollback()
            identity = await find_vk_identity(session, vk_id)
            if identity is None:
                raise
    identity.data = profile
    await session.commit()
    return identity.user
