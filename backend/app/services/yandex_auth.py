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


YANDEX_FLOW = OAuthFlow("yandex", INVALID_STATE, YANDEX_UNAVAILABLE)


def yandex_oauth_client(settings: Settings) -> OAuthClient:
    return OAuthClient(
        settings.yandex_oauth_authorize_url,
        settings.yandex_oauth_client_id,
        settings.yandex_oauth_redirect_uri,
    )


async def start_flow(
    settings: Settings,
    user_id: uuid.UUID | None = None,
    accept_terms: bool = False,
    accept_personal_data: bool = False,
) -> tuple[str, str]:
    require_yandex_enabled(settings)
    return await oauth_flow.start_flow(
        YANDEX_FLOW,
        yandex_oauth_client(settings),
        settings.redis_url,
        user_id,
        accept_terms,
        accept_personal_data,
    )


async def complete_flow(
    settings: Settings,
    client: YandexClient,
    code: str,
    state: str,
    nonce: str,
    user_id: uuid.UUID | None = None,
) -> tuple[str, dict, dict]:
    require_yandex_enabled(settings)
    record = await oauth_flow.take_flow(YANDEX_FLOW, settings.redis_url, state, nonce, user_id)
    access_token = await client.exchange_code(code, record["verifier"])
    yandex_id, profile = await client.fetch_profile(access_token)
    return yandex_id, profile, record


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
    return await oauth_flow.get_or_create_provider_user(
        session,
        AuthProvider.yandex,
        yandex_id,
        profile,
        User(display_name=display_name_of(profile)),
        accept_terms,
        accept_personal_data,
    )
