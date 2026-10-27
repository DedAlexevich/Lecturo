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
from app.services.vk_auth import code_challenge
from app.services.yandex_auth import YandexClient, get_yandex_client

CLIENT_ID = "yandex-client"
CLIENT_SECRET = "yandex-secret"
REDIRECT_URI = "https://lecturo.test/auth/yandex"
TOKEN_URL = "https://oauth.yandex.test/token"
USER_INFO_URL = "https://login.yandex.test/info"
ACCESS_TOKEN = "yandex-access-token"


class FakeYandex:
    def __init__(self, yandex_id: str) -> None:
        self.yandex_id = yandex_id
        self.requests: list[httpx.Request] = []
        self.token_status = 200
        self.token_payload: dict = {"access_token": ACCESS_TOKEN, "token_type": "bearer"}
        self.user_payload: dict = {
            "id": yandex_id,
            "login": "ivan.petrov",
            "display_name": "ivan",
            "real_name": "Иван Петров",
            "first_name": "Иван",
            "last_name": "Петров",
            "default_email": "ivan@yandex.test",
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url) == TOKEN_URL:
            return httpx.Response(self.token_status, json=self.token_payload)
        if str(request.url) == f"{USER_INFO_URL}?format=json":
            return httpx.Response(200, json=self.user_payload)
        return httpx.Response(404)

    def form(self, index: int) -> dict[str, str]:
        return {
            key: value[0] for key, value in parse_qs(self.requests[index].content.decode()).items()
        }


@pytest.fixture(autouse=True)
def yandex_settings(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "yandex_oauth_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "yandex_oauth_client_secret", "")
    monkeypatch.setattr(settings, "yandex_oauth_redirect_uri", REDIRECT_URI)
    monkeypatch.setattr(settings, "yandex_oauth_token_url", TOKEN_URL)
    monkeypatch.setattr(settings, "yandex_oauth_user_info_url", USER_INFO_URL)


@pytest.fixture(autouse=True)
async def reset_start_rate_limit() -> AsyncIterator[None]:
    redis = Redis.from_url(get_settings().redis_url)
    await redis.delete("rate:yandex-start:127.0.0.1")
    yield
    await redis.delete("rate:yandex-start:127.0.0.1")
    await redis.aclose()


@pytest.fixture
def yandex_id() -> str:
    return str(random.randint(10**8, 10**9))


@pytest.fixture
def yandex(yandex_id: str) -> Iterator[FakeYandex]:
    fake = FakeYandex(yandex_id)
    app.dependency_overrides[get_yandex_client] = lambda: YandexClient(
        get_settings(), transport=httpx.MockTransport(fake.handler)
    )
    yield fake
    app.dependency_overrides.pop(get_yandex_client, None)


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
    return {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}


NONCES: dict[str, str] = {}


def remember(response) -> str:
    state = parse_qs(urlparse(response.json()["url"]).query)["state"][0]
    NONCES[state] = response.json()["nonce"]
    return state


def callback_body(state: str, code: str = "auth-code") -> dict:
    return {"code": code, "state": state, "nonce": NONCES.get(state, "unknown")}


async def start_login(client, **consents) -> str:
    response = await client.post("/api/v1/auth/yandex/start", json=consents)
    assert response.status_code == 200
    return remember(response)


async def start_link(client, user: User) -> str:
    response = await client.post("/api/v1/me/identities/yandex/start", headers=headers(user))
    assert response.status_code == 200
    return remember(response)


async def users_with_yandex(yandex_id: str) -> list[AuthIdentity]:
    async with SessionLocal() as session:
        return list(
            await session.scalars(
                select(AuthIdentity).where(
                    AuthIdentity.provider == AuthProvider.yandex,
                    AuthIdentity.provider_user_id == yandex_id,
                )
            )
        )


async def test_providers_reports_yandex_flag(client, monkeypatch):
    assert (await client.get("/api/v1/auth/providers")).json()["yandex"] is True
    monkeypatch.setattr(get_settings(), "yandex_oauth_client_id", "")
    assert (await client.get("/api/v1/auth/providers")).json()["yandex"] is False


async def test_start_builds_pkce_authorize_url(client):
    response = await client.post("/api/v1/auth/yandex/start", json={})
    url = urlparse(response.json()["url"])
    query = {key: value[0] for key, value in parse_qs(url.query).items()}
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://oauth.yandex.ru/authorize"
    assert query["response_type"] == "code"
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == REDIRECT_URI
    assert query["code_challenge_method"] == "S256"
    assert len(query["code_challenge"]) == 43
    assert len(query["state"]) >= 32


async def test_start_without_configuration_returns_503(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "yandex_oauth_redirect_uri", "")
    assert (await client.post("/api/v1/auth/yandex/start", json={})).status_code == 503
    assert (
        await client.post("/api/v1/auth/yandex/callback", json=callback_body("x"))
    ).status_code == 503


async def test_login_creates_user_with_consents(client, yandex, yandex_id, cleanup):
    state = await start_login(client, accept_terms=True, accept_personal_data=True)
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    assert response.status_code == 200
    token = response.json()["access_token"]
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    body = me.json()
    cleanup.append(uuid.UUID(body["id"]))
    assert body["display_name"] == "Иван Петров"
    assert [item["provider"] for item in body["identities"]] == ["yandex"]
    identity = (await users_with_yandex(yandex_id))[0]
    assert identity.data == {
        "login": "ivan.petrov",
        "display_name": "ivan",
        "real_name": "Иван Петров",
        "first_name": "Иван",
        "last_name": "Петров",
    }
    async with SessionLocal() as session:
        user = await session.get(User, uuid.UUID(body["id"]))
        assert user.terms_accepted_at is not None
        assert user.personal_data_accepted_at is not None


async def test_login_name_falls_back_to_login(client, yandex, cleanup):
    yandex.user_payload = {"id": yandex.yandex_id, "login": "just.login"}
    state = await start_login(client, accept_terms=True, accept_personal_data=True)
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    token = response.json()["access_token"]
    me = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    cleanup.append(uuid.UUID(me.json()["id"]))
    assert me.json()["display_name"] == "just.login"


async def test_token_exchange_sends_pkce_verifier(client, yandex, cleanup):
    start = await client.post(
        "/api/v1/auth/yandex/start", json={"accept_terms": True, "accept_personal_data": True}
    )
    query = parse_qs(urlparse(start.json()["url"]).query)
    state = remember(start)
    challenge = query["code_challenge"][0]
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body(state, "abc"))
    assert response.status_code == 200
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    cleanup.append(uuid.UUID(me.json()["id"]))
    token_form = yandex.form(0)
    assert token_form["grant_type"] == "authorization_code"
    assert token_form["code"] == "abc"
    assert token_form["client_id"] == CLIENT_ID
    assert "client_secret" not in token_form
    assert code_challenge(token_form["code_verifier"]) == challenge
    assert yandex.requests[1].headers["Authorization"] == f"OAuth {ACCESS_TOKEN}"


async def test_token_exchange_sends_secret_when_configured(client, yandex, monkeypatch, cleanup):
    monkeypatch.setattr(get_settings(), "yandex_oauth_client_secret", CLIENT_SECRET)
    state = await start_login(client, accept_terms=True, accept_personal_data=True)
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    cleanup.append(uuid.UUID(me.json()["id"]))
    assert yandex.form(0)["client_secret"] == CLIENT_SECRET


async def test_login_new_user_without_consents_is_forbidden(client, yandex, yandex_id):
    state = await start_login(client)
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    assert response.status_code == 403
    assert await users_with_yandex(yandex_id) == []


async def test_login_with_one_consent_is_forbidden(client, yandex, yandex_id):
    state = await start_login(client, accept_personal_data=True)
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    assert response.status_code == 403
    assert await users_with_yandex(yandex_id) == []


async def test_login_existing_user_needs_no_consents(client, yandex, yandex_id, cleanup):
    user = await create_user(cleanup, [(AuthProvider.yandex, yandex_id)])
    state = await start_login(client)
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    assert response.status_code == 200
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    assert me.json()["id"] == str(user.id)


async def test_callback_state_is_single_use(client, yandex, yandex_id, cleanup):
    await create_user(cleanup, [(AuthProvider.yandex, yandex_id)])
    state = await start_login(client)
    assert (
        await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    ).status_code == 200
    assert (
        await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    ).status_code == 400


async def test_callback_unknown_state_is_rejected(client, yandex):
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body("unknown"))
    assert response.status_code == 400
    assert yandex.requests == []


async def test_login_rejects_link_state(client, yandex, cleanup):
    user = await create_user(cleanup, [(AuthProvider.email, "ya-a@example.test")])
    state = await start_link(client, user)
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    assert response.status_code == 400
    assert yandex.requests == []


async def test_yandex_rejecting_code_returns_401(client, yandex):
    yandex.token_status = 400
    yandex.token_payload = {"error": "invalid_grant"}
    state = await start_login(client, accept_terms=True, accept_personal_data=True)
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    assert response.status_code == 401


async def test_yandex_server_error_returns_502(client, yandex):
    yandex.token_status = 503
    state = await start_login(client, accept_terms=True, accept_personal_data=True)
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    assert response.status_code == 502


async def test_profile_without_id_returns_401(client, yandex):
    yandex.user_payload = {"login": "ivan"}
    state = await start_login(client, accept_terms=True, accept_personal_data=True)
    response = await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    assert response.status_code == 401


async def test_link_adds_identity(client, yandex, yandex_id, cleanup):
    user = await create_user(cleanup, [(AuthProvider.email, "ya-link@example.test")])
    state = await start_link(client, user)
    response = await client.post(
        "/api/v1/me/identities/yandex", json=callback_body(state), headers=headers(user)
    )
    assert response.status_code == 200
    assert sorted(item["provider"] for item in response.json()["identities"]) == [
        "email",
        "yandex",
    ]
    assert (await users_with_yandex(yandex_id))[0].user_id == user.id


async def test_link_same_identity_again_is_idempotent(client, yandex, yandex_id, cleanup):
    user = await create_user(cleanup, [(AuthProvider.yandex, yandex_id)])
    state = await start_link(client, user)
    response = await client.post(
        "/api/v1/me/identities/yandex", json=callback_body(state), headers=headers(user)
    )
    assert response.status_code == 200
    assert len(await users_with_yandex(yandex_id)) == 1


async def test_link_taken_by_other_user_returns_409(client, yandex, yandex_id, cleanup):
    owner = await create_user(cleanup, [(AuthProvider.yandex, yandex_id)])
    other = await create_user(cleanup, [(AuthProvider.email, "ya-other@example.test")])
    state = await start_link(client, other)
    response = await client.post(
        "/api/v1/me/identities/yandex", json=callback_body(state), headers=headers(other)
    )
    assert response.status_code == 409
    assert [item.user_id for item in await users_with_yandex(yandex_id)] == [owner.id]


async def test_link_second_yandex_to_same_user_returns_409(client, yandex, cleanup):
    user = await create_user(cleanup, [(AuthProvider.yandex, "1")])
    state = await start_link(client, user)
    response = await client.post(
        "/api/v1/me/identities/yandex", json=callback_body(state), headers=headers(user)
    )
    assert response.status_code == 409


async def test_link_state_of_another_user_is_rejected(client, yandex, cleanup):
    owner = await create_user(cleanup, [(AuthProvider.email, "ya-owner@example.test")])
    intruder = await create_user(cleanup, [(AuthProvider.email, "ya-intruder@example.test")])
    state = await start_link(client, owner)
    response = await client.post(
        "/api/v1/me/identities/yandex", json=callback_body(state), headers=headers(intruder)
    )
    assert response.status_code == 400
    assert yandex.requests == []


async def test_link_requires_authentication(client):
    assert (await client.post("/api/v1/me/identities/yandex/start")).status_code == 401
    response = await client.post("/api/v1/me/identities/yandex", json=callback_body("x"))
    assert response.status_code == 401


async def test_unlink_yandex(client, yandex_id, cleanup):
    user = await create_user(
        cleanup, [(AuthProvider.yandex, yandex_id), (AuthProvider.email, "ya-unlink@example.test")]
    )
    response = await client.delete("/api/v1/me/identities/yandex", headers=headers(user))
    assert response.status_code == 200
    assert [item["provider"] for item in response.json()["identities"]] == ["email"]


async def test_unlink_only_yandex_is_forbidden(client, yandex_id, cleanup):
    user = await create_user(cleanup, [(AuthProvider.yandex, yandex_id)])
    response = await client.delete("/api/v1/me/identities/yandex", headers=headers(user))
    assert response.status_code == 409


async def test_callback_with_wrong_nonce_is_rejected(client, yandex, yandex_id, cleanup):
    await create_user(cleanup, [(AuthProvider.yandex, yandex_id)])
    state = await start_login(client)
    body = callback_body(state) | {"nonce": "another-browser"}
    response = await client.post("/api/v1/auth/yandex/callback", json=body)
    assert response.status_code == 400
    assert yandex.requests == []


async def test_link_with_wrong_nonce_is_rejected(client, yandex, cleanup):
    user = await create_user(cleanup, [(AuthProvider.email, "ya-nonce@example.test")])
    state = await start_link(client, user)
    body = callback_body(state) | {"nonce": "another-browser"}
    response = await client.post("/api/v1/me/identities/yandex", json=body, headers=headers(user))
    assert response.status_code == 400
    assert yandex.requests == []


async def test_wrong_nonce_does_not_burn_state(client, yandex, yandex_id, cleanup):
    await create_user(cleanup, [(AuthProvider.yandex, yandex_id)])
    state = await start_login(client)
    wrong = callback_body(state) | {"nonce": "another-browser"}
    assert (await client.post("/api/v1/auth/yandex/callback", json=wrong)).status_code == 400
    assert (
        await client.post("/api/v1/auth/yandex/callback", json=callback_body(state))
    ).status_code == 200


async def test_link_start_is_rate_limited(client, cleanup, monkeypatch):
    monkeypatch.setattr(get_settings(), "yandex_oauth_start_rate_limit", 1)
    user = await create_user(cleanup, [(AuthProvider.email, "ya-rate@example.test")])
    first = await client.post("/api/v1/me/identities/yandex/start", headers=headers(user))
    second = await client.post("/api/v1/me/identities/yandex/start", headers=headers(user))
    assert [first.status_code, second.status_code] == [200, 429]
    redis = Redis.from_url(get_settings().redis_url)
    await redis.delete(f"rate:yandex-link-start:{user.id}")
    await redis.aclose()


async def test_start_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "yandex_oauth_start_rate_limit", 2)
    statuses = [
        (await client.post("/api/v1/auth/yandex/start", json={})).status_code for _ in range(3)
    ]
    assert statuses == [200, 200, 429]
