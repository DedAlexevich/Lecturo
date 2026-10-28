import logging
import uuid
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import AuthProvider, User
from app.services import oauth_flow
from app.services.oauth_flow import OAuthClient, OAuthFlow

logger = logging.getLogger(__name__)

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


VK_FLOW = OAuthFlow("vk", INVALID_STATE, VK_UNAVAILABLE)


def vk_oauth_client(settings: Settings) -> OAuthClient:
    return OAuthClient(settings.vk_authorize_url, settings.vk_client_id, settings.vk_redirect_uri)


async def start_flow(
    settings: Settings,
    user_id: uuid.UUID | None = None,
    accept_terms: bool = False,
    accept_personal_data: bool = False,
) -> tuple[str, str]:
    require_vk_enabled(settings)
    return await oauth_flow.start_flow(
        VK_FLOW,
        vk_oauth_client(settings),
        settings.redis_url,
        user_id,
        accept_terms,
        accept_personal_data,
    )


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
    record = await oauth_flow.take_flow(VK_FLOW, settings.redis_url, state, nonce, user_id)
    access_token = await client.exchange_code(code, record["verifier"], device_id, state)
    vk_id, profile = await client.fetch_profile(access_token)
    return vk_id, profile, record


async def get_or_create_vk_user(
    session: AsyncSession,
    vk_id: str,
    profile: dict,
    accept_terms: bool = False,
    accept_personal_data: bool = False,
) -> User:
    display_name = " ".join(
        part for part in (profile.get("first_name"), profile.get("last_name")) if part
    )
    return await oauth_flow.get_or_create_provider_user(
        session,
        AuthProvider.vk,
        vk_id,
        profile,
        User(display_name=(display_name or "Пользователь VK")[:120]),
        accept_terms,
        accept_personal_data,
    )
