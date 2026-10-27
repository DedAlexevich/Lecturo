import random
import uuid
from collections.abc import AsyncIterator, Iterator
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.main import app
from app.models import AuthIdentity, AuthProvider, User
from app.services.vk_auth import VkClient, code_challenge, get_vk_client

pytestmark = pytest.mark.usefixtures("reset_auth_rate_limits")


CLIENT_ID = "54321"
REDIRECT_URI = "https://lecturo.test/auth/vk"
TOKEN_URL = "https://id.vk.test/oauth2/auth"
USER_INFO_URL = "https://id.vk.test/oauth2/user_info"
ACCESS_TOKEN = "vk-access-token"


class FakeVk:
    def __init__(self, vk_id: str) -> None:
        self.vk_id = vk_id
        self.requests: list[httpx.Request] = []
        self.token_status = 200
        self.token_payload: dict = {"access_token": ACCESS_TOKEN, "user_id": int(vk_id)}
        self.user_payload: dict = {
            "user": {
                "user_id": vk_id,
                "first_name": "Иван",
                "last_name": "Петров",
                "avatar": "https://vk.test/a.jpg",
                "email": "ivan@example.test",
            }
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url) == TOKEN_URL:
            return httpx.Response(self.token_status, json=self.token_payload)
        if str(request.url) == USER_INFO_URL:
            return httpx.Response(200, json=self.user_payload)
        return httpx.Response(404)

    def form(self, index: int) -> dict[str, str]:
        return {
            key: value[0] for key, value in parse_qs(self.requests[index].content.decode()).items()
        }


@pytest.fixture(autouse=True)
def vk_settings(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "vk_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "vk_redirect_uri", REDIRECT_URI)
    monkeypatch.setattr(settings, "vk_token_url", TOKEN_URL)
    monkeypatch.setattr(settings, "vk_user_info_url", USER_INFO_URL)


@pytest.fixture(autouse=True)
async def reset_start_rate_limit() -> AsyncIterator[None]:
    redis = Redis.from_url(get_settings().redis_url)
    await redis.delete("rate:vk-start:127.0.0.1")
    yield
    await redis.delete("rate:vk-start:127.0.0.1")
    await redis.aclose()


@pytest.fixture
def vk_id() -> str:
    return str(random.randint(10**8, 10**9))


@pytest.fixture
def vk(vk_id: str) -> Iterator[FakeVk]:
    fake = FakeVk(vk_id)
    app.dependency_overrides[get_vk_client] = lambda: VkClient(
        get_settings(), transport=httpx.MockTransport(fake.handler)
    )
    yield fake
    app.dependency_overrides.pop(get_vk_client, None)


@pytest.fixture
async def cleanup() -> AsyncIterator[list[uuid.UUID]]:
    user_ids: list[uuid.UUID] = []
    yield user_ids
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()


async def create_user(cleanup: list[uuid.UUID], providers=()) -> User:
    async with SessionLocal() as session:
        user = User(display_name="Тест")
        for provider, value in providers:
            user.identities.append(AuthIdentity(provider=provider, provider_user_id=value))
        session.add(user)
        await session.commit()
        cleanup.append(user.id)
        return user


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


NONCES: dict[str, str] = {}


def remember(response) -> str:
    state = parse_qs(urlparse(response.json()["url"]).query)["state"][0]
    NONCES[state] = response.json()["nonce"]
    return state


def callback_body(state: str, code: str = "auth-code") -> dict:
    return {
        "code": code,
        "state": state,
        "device_id": "device-1",
        "nonce": NONCES.get(state, "unknown"),
    }


async def finish_login(client, state: str) -> int:
    response = await client.post("/api/v1/auth/vk/callback", json=callback_body(state))
    return response.status_code


async def start_login(client, **consents) -> str:
    response = await client.post("/api/v1/auth/vk/start", json=consents)
    assert response.status_code == 200
    return remember(response)


async def start_link(client, user: User) -> str:
    response = await client.post("/api/v1/me/identities/vk/start", headers=headers(user))
    assert response.status_code == 200
    return remember(response)


async def users_with_vk(vk_id: str) -> list[AuthIdentity]:
    async with SessionLocal() as session:
        return list(
            await session.scalars(
                select(AuthIdentity).where(
                    AuthIdentity.provider == AuthProvider.vk,
                    AuthIdentity.provider_user_id == vk_id,
                )
            )
        )


async def test_providers_reports_vk_flag(client, monkeypatch):
    assert (await client.get("/api/v1/auth/providers")).json()["vk"] is True
    monkeypatch.setattr(get_settings(), "vk_client_id", "")
    assert (await client.get("/api/v1/auth/providers")).json()["vk"] is False


async def test_start_builds_pkce_authorize_url(client):
    response = await client.post("/api/v1/auth/vk/start", json={})
    url = urlparse(response.json()["url"])
    query = {key: value[0] for key, value in parse_qs(url.query).items()}
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://id.vk.com/authorize"
    assert query["response_type"] == "code"
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == REDIRECT_URI
    assert query["code_challenge_method"] == "S256"
    assert len(query["code_challenge"]) == 43
    assert len(query["state"]) >= 32


async def test_start_without_configuration_returns_503(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "vk_redirect_uri", "")
    assert (await client.post("/api/v1/auth/vk/start", json={})).status_code == 503
    assert (
        await client.post("/api/v1/auth/vk/callback", json=callback_body("x"))
    ).status_code == 503


async def test_login_creates_user_with_consents(client, vk, vk_id, cleanup):
    state = await start_login(client, accept_terms=True, accept_personal_data=True)
    response = await client.post("/api/v1/auth/vk/callback", json=callback_body(state))
    assert response.status_code == 200
    token = response.json()["access_token"]
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    body = me.json()
    cleanup.append(uuid.UUID(body["id"]))
    assert body["display_name"] == "Иван Петров"
    assert [item["provider"] for item in body["identities"]] == ["vk"]
    identity = (await users_with_vk(vk_id))[0]
    assert identity.data == {
        "first_name": "Иван",
        "last_name": "Петров",
        "avatar": "https://vk.test/a.jpg",
    }
    async with SessionLocal() as session:
        user = await session.get(User, uuid.UUID(body["id"]))
        assert user.terms_accepted_at is not None
        assert user.personal_data_accepted_at is not None


async def test_token_exchange_sends_pkce_verifier(client, vk, cleanup):
    start = await client.post(
        "/api/v1/auth/vk/start", json={"accept_terms": True, "accept_personal_data": True}
    )
    query = parse_qs(urlparse(start.json()["url"]).query)
    state = remember(start)
    challenge = query["code_challenge"][0]
    response = await client.post("/api/v1/auth/vk/callback", json=callback_body(state, "abc"))
    assert response.status_code == 200
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    cleanup.append(uuid.UUID(me.json()["id"]))
    token_form = vk.form(0)
    assert token_form["grant_type"] == "authorization_code"
    assert token_form["code"] == "abc"
    assert token_form["client_id"] == CLIENT_ID
    assert token_form["device_id"] == "device-1"
    assert token_form["redirect_uri"] == REDIRECT_URI
    assert token_form["state"] == state
    assert code_challenge(token_form["code_verifier"]) == challenge
    assert vk.form(1) == {"client_id": CLIENT_ID, "access_token": ACCESS_TOKEN}


async def test_login_new_user_without_consents_is_forbidden(client, vk, vk_id):
    state = await start_login(client)
    response = await client.post("/api/v1/auth/vk/callback", json=callback_body(state))
    assert response.status_code == 403
    assert await users_with_vk(vk_id) == []


async def test_login_with_one_consent_is_forbidden(client, vk, vk_id):
    state = await start_login(client, accept_terms=True)
    response = await client.post("/api/v1/auth/vk/callback", json=callback_body(state))
    assert response.status_code == 403
    assert await users_with_vk(vk_id) == []


async def test_login_existing_user_needs_no_consents(client, vk, vk_id, cleanup):
    user = await create_user(cleanup, [(AuthProvider.vk, vk_id)])
    state = await start_login(client)
    response = await client.post("/api/v1/auth/vk/callback", json=callback_body(state))
    assert response.status_code == 200
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    assert me.json()["id"] == str(user.id)


async def test_callback_state_is_single_use(client, vk, vk_id, cleanup):
    await create_user(cleanup, [(AuthProvider.vk, vk_id)])
    state = await start_login(client)
    assert (
        await client.post("/api/v1/auth/vk/callback", json=callback_body(state))
    ).status_code == 200
    assert (
        await client.post("/api/v1/auth/vk/callback", json=callback_body(state))
    ).status_code == 400


async def test_callback_unknown_state_is_rejected(client, vk):
    response = await client.post("/api/v1/auth/vk/callback", json=callback_body("unknown"))
    assert response.status_code == 400
    assert vk.requests == []


async def test_login_rejects_link_state(client, vk, cleanup):
    user = await create_user(cleanup, [(AuthProvider.email, "a@example.test")])
    state = await start_link(client, user)
    response = await client.post("/api/v1/auth/vk/callback", json=callback_body(state))
    assert response.status_code == 400
    assert vk.requests == []


async def test_vk_rejecting_code_returns_401(client, vk):
    vk.token_status = 400
    vk.token_payload = {"error": "invalid_grant"}
    state = await start_login(client, accept_terms=True, accept_personal_data=True)
    response = await client.post("/api/v1/auth/vk/callback", json=callback_body(state))
    assert response.status_code == 401


async def test_vk_server_error_returns_502(client, vk):
    vk.token_status = 503
    state = await start_login(client, accept_terms=True, accept_personal_data=True)
    response = await client.post("/api/v1/auth/vk/callback", json=callback_body(state))
    assert response.status_code == 502


async def test_profile_without_user_id_returns_401(client, vk):
    vk.user_payload = {"user": {"first_name": "Иван"}}
    state = await start_login(client, accept_terms=True, accept_personal_data=True)
    response = await client.post("/api/v1/auth/vk/callback", json=callback_body(state))
    assert response.status_code == 401


async def test_link_adds_identity(client, vk, vk_id, cleanup):
    user = await create_user(cleanup, [(AuthProvider.email, "link@example.test")])
    state = await start_link(client, user)
    response = await client.post(
        "/api/v1/me/identities/vk", json=callback_body(state), headers=headers(user)
    )
    assert response.status_code == 200
    assert sorted(item["provider"] for item in response.json()["identities"]) == ["email", "vk"]
    assert (await users_with_vk(vk_id))[0].user_id == user.id


async def test_link_same_identity_again_is_idempotent(client, vk, vk_id, cleanup):
    user = await create_user(cleanup, [(AuthProvider.vk, vk_id)])
    state = await start_link(client, user)
    response = await client.post(
        "/api/v1/me/identities/vk", json=callback_body(state), headers=headers(user)
    )
    assert response.status_code == 200
    assert len(await users_with_vk(vk_id)) == 1


async def test_link_taken_by_other_user_returns_409(client, vk, vk_id, cleanup):
    owner = await create_user(cleanup, [(AuthProvider.vk, vk_id)])
    other = await create_user(cleanup, [(AuthProvider.email, "other@example.test")])
    state = await start_link(client, other)
    response = await client.post(
        "/api/v1/me/identities/vk", json=callback_body(state), headers=headers(other)
    )
    assert response.status_code == 409
    assert [item.user_id for item in await users_with_vk(vk_id)] == [owner.id]


async def test_link_second_vk_to_same_user_returns_409(client, vk, cleanup):
    user = await create_user(cleanup, [(AuthProvider.vk, "1")])
    state = await start_link(client, user)
    response = await client.post(
        "/api/v1/me/identities/vk", json=callback_body(state), headers=headers(user)
    )
    assert response.status_code == 409


async def test_link_state_of_another_user_is_rejected(client, vk, cleanup):
    owner = await create_user(cleanup, [(AuthProvider.email, "owner@example.test")])
    intruder = await create_user(cleanup, [(AuthProvider.email, "intruder@example.test")])
    state = await start_link(client, owner)
    response = await client.post(
        "/api/v1/me/identities/vk", json=callback_body(state), headers=headers(intruder)
    )
    assert response.status_code == 400
    assert vk.requests == []


async def test_link_requires_authentication(client):
    assert (await client.post("/api/v1/me/identities/vk/start")).status_code == 401
    response = await client.post("/api/v1/me/identities/vk", json=callback_body("x"))
    assert response.status_code == 401


async def test_unlink_vk(client, vk_id, cleanup):
    user = await create_user(
        cleanup, [(AuthProvider.vk, vk_id), (AuthProvider.email, "unlink@example.test")]
    )
    response = await client.delete("/api/v1/me/identities/vk", headers=headers(user))
    assert response.status_code == 200
    assert [item["provider"] for item in response.json()["identities"]] == ["email"]


async def test_unlink_only_vk_is_forbidden(client, vk_id, cleanup):
    user = await create_user(cleanup, [(AuthProvider.vk, vk_id)])
    response = await client.delete("/api/v1/me/identities/vk", headers=headers(user))
    assert response.status_code == 409


async def test_callback_with_wrong_nonce_is_rejected(client, vk, vk_id, cleanup):
    await create_user(cleanup, [(AuthProvider.vk, vk_id)])
    state = await start_login(client)
    body = callback_body(state) | {"nonce": "another-browser"}
    response = await client.post("/api/v1/auth/vk/callback", json=body)
    assert response.status_code == 400
    assert vk.requests == []


async def test_link_with_wrong_nonce_is_rejected(client, vk, cleanup):
    user = await create_user(cleanup, [(AuthProvider.email, "nonce@example.test")])
    state = await start_link(client, user)
    body = callback_body(state) | {"nonce": "another-browser"}
    response = await client.post("/api/v1/me/identities/vk", json=body, headers=headers(user))
    assert response.status_code == 400
    assert vk.requests == []


async def test_start_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "vk_start_rate_limit", 2)
    statuses = [(await client.post("/api/v1/auth/vk/start", json={})).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]


async def test_link_start_is_rate_limited(client, cleanup, monkeypatch):
    monkeypatch.setattr(get_settings(), "vk_start_rate_limit", 1)
    user = await create_user(cleanup, [(AuthProvider.email, "vk-rate@example.test")])
    redis = Redis.from_url(get_settings().redis_url)
    try:
        first = await client.post("/api/v1/me/identities/vk/start", headers=headers(user))
        second = await client.post("/api/v1/me/identities/vk/start", headers=headers(user))
    finally:
        await redis.delete(f"rate:vk-link-start:{user.id}")
        await redis.aclose()
    assert [first.status_code, second.status_code] == [200, 429]
