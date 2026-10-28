import base64
import hashlib
import json
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.redis import get_redis
from app.models import AuthIdentity, AuthProvider, User
from app.services.consents import record_signup_consents, require_provider_signup_consents
from app.services.quota import carry_weekly_usage

STATE_TTL_SECONDS = 10 * 60


@dataclass(frozen=True)
class OAuthFlow:
    state_prefix: str
    invalid_state: str
    unavailable: str

    def state_key(self, state: str) -> str:
        return f"{self.state_prefix}:state:{state}"


@dataclass(frozen=True)
class OAuthClient:
    authorize_url: str
    client_id: str
    redirect_uri: str


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def owner_of(user_id: uuid.UUID | None) -> str | None:
    return str(user_id) if user_id else None


async def start_flow(
    flow: OAuthFlow,
    client: OAuthClient,
    redis_url: str,
    user_id: uuid.UUID | None = None,
    accept_terms: bool = False,
    accept_personal_data: bool = False,
) -> tuple[str, str]:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    record = {
        "verifier": verifier,
        "nonce": nonce,
        "user_id": owner_of(user_id),
        "accept_terms": accept_terms,
        "accept_personal_data": accept_personal_data,
    }
    try:
        await get_redis(redis_url).set(
            flow.state_key(state), json.dumps(record), ex=STATE_TTL_SECONDS
        )
    except (OSError, RedisError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, flow.unavailable) from None
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client.client_id,
            "redirect_uri": client.redirect_uri,
            "state": state,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{client.authorize_url}?{query}", nonce


async def take_flow(
    flow: OAuthFlow, redis_url: str, state: str, nonce: str, user_id: uuid.UUID | None
) -> dict:
    redis = get_redis(redis_url)
    invalid = HTTPException(status.HTTP_400_BAD_REQUEST, flow.invalid_state)
    try:
        raw = await redis.get(flow.state_key(state))
        if raw is None:
            raise invalid
        try:
            record = json.loads(raw)
            matches = secrets.compare_digest(record["nonce"], nonce)
            owner = record["user_id"]
        except (ValueError, KeyError, TypeError):
            raise invalid from None
        if not matches or owner != owner_of(user_id):
            raise invalid
        if await redis.getdel(flow.state_key(state)) is None:
            raise invalid
    except (OSError, RedisError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, flow.unavailable) from None
    return record


async def find_provider_identity(
    session: AsyncSession, provider: AuthProvider, provider_user_id: str
) -> AuthIdentity | None:
    return await session.scalar(
        select(AuthIdentity)
        .where(
            AuthIdentity.provider == provider,
            AuthIdentity.provider_user_id == provider_user_id,
        )
        .options(selectinload(AuthIdentity.user))
    )


async def get_or_create_provider_user(
    session: AsyncSession,
    provider: AuthProvider,
    provider_user_id: str,
    profile: dict,
    new_user: User,
    accept_terms: bool = False,
    accept_personal_data: bool = False,
    update_user: Callable[[User], None] | None = None,
) -> User:
    identity = await find_provider_identity(session, provider, provider_user_id)
    if identity is None:
        require_provider_signup_consents(accept_terms, accept_personal_data)
        record_signup_consents(new_user)
        new_user.identities.append(
            AuthIdentity(provider=provider, provider_user_id=provider_user_id, data=profile)
        )
        session.add(new_user)
        try:
            await session.flush()
            await carry_weekly_usage(session, new_user, provider, provider_user_id)
            await session.commit()
            return new_user
        except IntegrityError:
            await session.rollback()
            identity = await find_provider_identity(session, provider, provider_user_id)
            if identity is None:
                raise
    identity.data = profile
    if update_user is not None:
        update_user(identity.user)
    await session.commit()
    return identity.user
