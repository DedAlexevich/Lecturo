import random
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.cli import make_admin
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.main import app
from app.models import AdminAction, AdminAuditEntry, AuthIdentity, AuthProvider, User
from app.services.admin import (
    bootstrap_admins,
    grant_admin,
    record_action,
    revoke_admin,
    without_secrets,
)

MakeUser = Callable[..., Awaitable[User]]


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}


@pytest.fixture
async def make_user() -> AsyncIterator[MakeUser]:
    created: list[uuid.UUID] = []

    async def create(*, is_admin: bool = False, telegram_id: int | None = None) -> User:
        async with SessionLocal() as session:
            user = User(
                email=f"admin-{uuid.uuid4().hex[:12]}@example.org",
                display_name="Админ",
                is_admin=is_admin,
            )
            if telegram_id is not None:
                user.identities.append(
                    AuthIdentity(provider=AuthProvider.telegram, provider_user_id=str(telegram_id))
                )
            session.add(user)
            await session.commit()
            created.append(user.id)
            return user

    yield create
    async with SessionLocal() as session:
        ids = [str(user_id) for user_id in created]
        await session.execute(delete(AdminAuditEntry).where(AdminAuditEntry.target_id.in_(ids)))
        await session.execute(delete(User).where(User.id.in_(created)))
        await session.commit()


@pytest.fixture
async def no_other_admins() -> AsyncIterator[None]:
    async with SessionLocal() as session:
        others = list(await session.scalars(select(User.id).where(User.is_admin)))
        await session.execute(update(User).where(User.id.in_(others)).values(is_admin=False))
        await session.commit()
    yield
    async with SessionLocal() as session:
        await session.execute(update(User).where(User.id.in_(others)).values(is_admin=True))
        await session.commit()


def admin_routes() -> list[tuple[str, str]]:
    return [
        (method.upper(), path.replace("{user_id}", str(uuid.uuid4())))
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/v1/admin")
        for method in operations
    ]


async def audit(client: AsyncClient, admin: User, **params) -> dict:
    response = await client.get("/api/v1/admin/audit", params=params, headers=headers(admin))
    assert response.status_code == 200
    return response.json()


async def test_admin_routes_return_404_for_anonymous_and_regular_users(
    client: AsyncClient, make_user: MakeUser
):
    regular = await make_user()
    routes = admin_routes()
    assert {path.split("/")[4] for _, path in routes} >= {"audit", "admins"}
    for method, path in routes:
        for auth in ({}, headers(regular), {"Authorization": "Bearer broken"}):
            response = await client.request(
                method, path, headers=auth, json={"identifier": regular.email}
            )
            assert response.status_code == 404, (method, path)
            assert response.json() == {"detail": "Not Found"}


async def test_me_shows_admin_flag(client: AsyncClient, make_user: MakeUser):
    regular = await make_user()
    admin = await make_user(is_admin=True)

    regular_me = await client.get("/api/v1/me", headers=headers(regular))
    admin_me = await client.get("/api/v1/me", headers=headers(admin))

    assert regular_me.json()["is_admin"] is False
    assert admin_me.json()["is_admin"] is True


async def test_admin_grants_by_email_and_telegram_and_it_is_logged(
    client: AsyncClient, make_user: MakeUser
):
    admin = await make_user(is_admin=True)
    by_email = await make_user()
    telegram_id = random.randint(10**9, 10**10)
    by_telegram = await make_user(telegram_id=telegram_id)

    first = await client.post(
        "/api/v1/admin/admins",
        json={"identifier": f"  {by_email.email.upper()} "},
        headers=headers(admin),
    )
    second = await client.post(
        "/api/v1/admin/admins", json={"identifier": str(telegram_id)}, headers=headers(admin)
    )

    assert first.status_code == 201
    assert first.json()["id"] == str(by_email.id)
    assert second.status_code == 201
    assert second.json()["id"] == str(by_telegram.id)
    listed = await client.get("/api/v1/admin/admins", headers=headers(admin))
    assert {str(by_email.id), str(by_telegram.id), str(admin.id)} <= {
        item["id"] for item in listed.json()
    }
    page = await audit(client, admin, actor_id=str(admin.id))
    assert page["total"] == 2
    newest, oldest = page["items"]
    assert newest["target_id"] == str(by_telegram.id)
    assert oldest["target_id"] == str(by_email.id)
    assert oldest["action"] == "admin_granted"
    assert oldest["actor_label"] == admin.email
    assert oldest["target_label"] == by_email.email
    assert oldest["details"] == {"source": "panel"}
    granted_me = await client.get("/api/v1/me", headers=headers(by_email))
    assert granted_me.json()["is_admin"] is True


async def test_grant_rejects_unknown_and_existing_admin(client: AsyncClient, make_user: MakeUser):
    admin = await make_user(is_admin=True)
    other_admin = await make_user(is_admin=True)

    unknown = await client.post(
        "/api/v1/admin/admins", json={"identifier": "nobody@example.org"}, headers=headers(admin)
    )
    garbage = await client.post(
        "/api/v1/admin/admins", json={"identifier": "nobody"}, headers=headers(admin)
    )
    again = await client.post(
        "/api/v1/admin/admins", json={"identifier": other_admin.email}, headers=headers(admin)
    )

    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Пользователь не найден"
    assert garbage.status_code == 404
    assert again.status_code == 409
    assert (await audit(client, admin, actor_id=str(admin.id)))["total"] == 0


async def test_revoke_takes_access_away_at_once(client: AsyncClient, make_user: MakeUser):
    admin = await make_user(is_admin=True)
    other = await make_user(is_admin=True)
    other_headers = headers(other)
    assert (await client.get("/api/v1/admin/admins", headers=other_headers)).status_code == 200

    response = await client.delete(f"/api/v1/admin/admins/{other.id}", headers=headers(admin))

    assert response.status_code == 204
    assert (await client.get("/api/v1/admin/admins", headers=other_headers)).status_code == 404
    entry = (await audit(client, admin, actor_id=str(admin.id), action="admin_revoked"))["items"]
    assert [item["target_id"] for item in entry] == [str(other.id)]
    missing = await client.delete(f"/api/v1/admin/admins/{other.id}", headers=headers(admin))
    assert missing.status_code == 404


async def test_last_admin_cannot_revoke_self(
    client: AsyncClient, make_user: MakeUser, no_other_admins: None
):
    admin = await make_user(is_admin=True)

    response = await client.delete(f"/api/v1/admin/admins/{admin.id}", headers=headers(admin))

    assert response.status_code == 409
    assert response.json()["detail"] == "Нельзя снять последнего администратора"
    me = await client.get("/api/v1/me", headers=headers(admin))
    assert me.json()["is_admin"] is True


async def test_two_admins_revoking_each_other_keep_one(
    make_user: MakeUser, race, no_other_admins: None
):
    first = await make_user(is_admin=True)
    second = await make_user(is_admin=True)

    results = await race(
        lambda session: revoke_admin(session, first, second.id),
        lambda session: revoke_admin(session, second, first.id),
    )

    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(failures) == 1
    assert failures[0].status_code == 404
    async with SessionLocal() as session:
        left = await session.scalar(
            select(User.id).where(User.id.in_([first.id, second.id]), User.is_admin)
        )
    assert left is not None


async def revoke_admin_in_new_session(actor: User, target_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        await revoke_admin(session, actor, target_id)


async def test_revoked_admin_cannot_act_with_old_user_object(make_user: MakeUser):
    first = await make_user(is_admin=True)
    second = await make_user(is_admin=True)
    third = await make_user(is_admin=True)
    regular = await make_user()

    await revoke_admin_in_new_session(first, second.id)
    with pytest.raises(HTTPException) as revoke_error:
        await revoke_admin_in_new_session(second, third.id)
    with pytest.raises(HTTPException) as grant_error:
        async with SessionLocal() as session:
            target = await session.get(User, regular.id)
            assert target is not None
            await grant_admin(session, second, target, "panel")

    assert revoke_error.value.status_code == 404
    assert grant_error.value.status_code == 404
    async with SessionLocal() as session:
        flags = dict(
            (
                await session.execute(
                    select(User.id, User.is_admin).where(User.id.in_([third.id, regular.id]))
                )
            ).all()
        )
    assert flags == {third.id: True, regular.id: False}


async def test_audit_filters_and_pages(client: AsyncClient, make_user: MakeUser):
    admin = await make_user(is_admin=True)
    targets = [await make_user() for _ in range(3)]
    async with SessionLocal() as session:
        actor = await session.get(User, admin.id)
        for target in targets:
            record_action(session, actor, AdminAction.admin_granted, "user", str(target.id))
        record_action(session, actor, AdminAction.admin_revoked, "user", str(targets[0].id))
        await session.commit()

    first_page = await audit(client, admin, actor_id=str(admin.id), limit=2)
    second_page = await audit(client, admin, actor_id=str(admin.id), limit=2, offset=2)
    granted = await audit(client, admin, actor_id=str(admin.id), action="admin_granted")

    assert first_page["total"] == 4
    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 2
    assert {item["id"] for item in first_page["items"]}.isdisjoint(
        item["id"] for item in second_page["items"]
    )
    assert granted["total"] == 3
    bad = await client.get("/api/v1/admin/audit", params={"limit": 1000}, headers=headers(admin))
    assert bad.status_code == 422


def test_audit_details_drop_secrets():
    details = {
        "source": "panel",
        "password": "hunter2",
        "access_token": "abc",
        "nested": {"api_key": "k", "telegram_init_data": "x", "reason": "ok"},
        "items": [{"secret": "s", "name": "n"}],
        "code": "123",
        "country_code": "RU",
        "monkey": 1,
    }

    assert without_secrets(details) == {
        "source": "panel",
        "country_code": "RU",
        "monkey": 1,
        "nested": {"reason": "ok"},
        "items": [{"name": "n"}],
    }


async def test_bootstrap_grants_only_when_no_admins(make_user: MakeUser, no_other_admins: None):
    telegram_id = random.randint(10**9, 10**10)
    first = await make_user()
    second = await make_user(telegram_id=telegram_id)
    late = await make_user()

    async with SessionLocal() as session:
        granted = await bootstrap_admins(
            session, [first.email, str(telegram_id), "missing@example.org"]
        )
    async with SessionLocal() as session:
        again = await bootstrap_admins(session, [late.email])

    assert granted == 2
    assert again == 0
    async with SessionLocal() as session:
        admins = set(
            await session.scalars(
                select(User.id).where(User.id.in_([first.id, second.id, late.id]), User.is_admin)
            )
        )
        sources = list(
            await session.scalars(
                select(AdminAuditEntry.details["source"].astext).where(
                    AdminAuditEntry.target_id == str(first.id)
                )
            )
        )
    assert admins == {first.id, second.id}
    assert sources == ["env"]


async def test_cli_make_admin(make_user: MakeUser, capsys: pytest.CaptureFixture[str]):
    user = await make_user()

    assert await make_admin(user.email) == 0
    assert await make_admin(user.email) == 1
    assert await make_admin("missing@example.org") == 1

    async with SessionLocal() as session:
        refreshed = await session.get(User, user.id)
        entry = await session.scalar(
            select(AdminAuditEntry).where(AdminAuditEntry.target_id == str(user.id))
        )
    assert refreshed is not None and refreshed.is_admin
    assert entry is not None and entry.actor_id is None and entry.details == {"source": "cli"}
    assert "теперь администратор" in capsys.readouterr().out
