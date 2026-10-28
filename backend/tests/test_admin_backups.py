import asyncio
import os
import secrets
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from arq import Retry
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import AdminAction, AdminAuditEntry, User
from app.pipeline.tasks import process_lecture
from app.services import admin_backups, maintenance
from app.services.auth import hash_password

PASSWORD = "правильный-пароль-1"

needs_postgres_tools = pytest.mark.skipif(
    shutil.which("pg_dump") is None or shutil.which("pg_restore") is None,
    reason="нужны pg_dump и pg_restore",
)


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}


@pytest.fixture
async def admin() -> AsyncIterator[User]:
    async with SessionLocal() as session:
        user = User(
            email=f"backup-{uuid.uuid4().hex[:10]}@example.org",
            display_name="Админ",
            is_admin=True,
            password_hash=hash_password(PASSWORD),
        )
        session.add(user)
        await session.commit()
    yield user
    async with SessionLocal() as session:
        await session.execute(delete(AdminAuditEntry).where(AdminAuditEntry.actor_id == user.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


@pytest.fixture(autouse=True)
async def clean_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Path]:
    directory = tmp_path / "backups"
    directory.mkdir()
    monkeypatch.setattr(get_settings(), "backup_dir", directory)
    admin_backups.integrity_cache.clear()
    redis = Redis.from_url(get_settings().redis_url)
    await redis.delete(admin_backups.JOB_KEY, admin_backups.LOCK_KEY, maintenance.MAINTENANCE_KEY)
    maintenance.cache["checked_at"] = 0.0
    yield directory
    await redis.delete(admin_backups.JOB_KEY, admin_backups.LOCK_KEY, maintenance.MAINTENANCE_KEY)
    await redis.aclose()
    maintenance.cache["checked_at"] = 0.0


async def audit_actions(admin: User) -> list[str]:
    async with SessionLocal() as session:
        return list(
            await session.scalars(
                select(AdminAuditEntry.action)
                .where(AdminAuditEntry.actor_id == admin.id)
                .order_by(AdminAuditEntry.created_at)
            )
        )


async def wait_for_job(client: AsyncClient, admin: User) -> dict:
    for _ in range(300):
        job = (await client.get("/api/v1/admin/backups/job", headers=headers(admin))).json()
        if job and job["state"] != "running":
            return job
        await asyncio.sleep(0.1)
    raise AssertionError("задача не завершилась")


async def make_dump(directory: Path) -> Path:
    path = directory / "lecturo-20260101-000000.dump"
    await admin_backups.dump_to(path, admin_backups.database_target())
    return path


def names(directory: Path, pattern: str = "*") -> list[str]:
    return sorted(path.name for path in directory.glob(pattern))


def test_names_are_validated():
    for name in ("../etc/passwd", "a/b.dump", "..dump", ".hidden.dump", "x.sql", "", "a b.dump"):
        with pytest.raises(admin_backups.BackupError):
            admin_backups.validate_name(name)
    assert admin_backups.validate_name("lecturo-20260101-000000.dump")
    assert admin_backups.validate_name("lecturo-20260101-000000.tar.age")


def test_listing_header_is_parsed():
    listing = (
        ";\n; Archive created at 2026-10-28 10:00:00 UTC\n;     dbname: lecturo\n"
        ";     Dumped from database version: 16.4 (Debian 16.4-1)\n"
        ";     Dumped by pg_dump version: 16.4\n;\n"
        "3; 2615 2200 SCHEMA - public lecturo\n"
    )

    info = admin_backups.parse_listing(listing)

    assert info.dump_major == 16


def test_dump_from_newer_postgres_is_rejected():
    info = admin_backups.DumpInfo(ok=True, dump_major=17)

    with pytest.raises(admin_backups.BackupError) as error:
        admin_backups.check_dump_version(info, 16)

    assert error.value.message == admin_backups.NEWER_DUMP
    admin_backups.check_dump_version(admin_backups.DumpInfo(ok=True, dump_major=15), 16)


async def test_backup_routes_are_404_for_regular_user(
    client: AsyncClient, user: User, auth_headers: dict
):
    assert (await client.get("/api/v1/admin/backups", headers=auth_headers)).status_code == 404
    assert (await client.post("/api/v1/admin/backups", headers=auth_headers)).status_code == 404
    response = await client.post(
        "/api/v1/admin/backups/lecturo-1.dump/restore",
        headers=auth_headers,
        json={"password": PASSWORD, "confirmation": "RESTORE"},
    )
    assert response.status_code == 404
    assert not admin_backups.background


@needs_postgres_tools
async def test_create_list_download_and_delete(client: AsyncClient, admin: User):
    started = await client.post("/api/v1/admin/backups", headers=headers(admin))
    job = await wait_for_job(client, admin)
    listing = await client.get("/api/v1/admin/backups", headers=headers(admin))

    assert started.status_code == 202
    assert job["state"] == "done"
    item = listing.json()["items"][0]
    assert item["name"] == job["backup"]
    assert item["name"].startswith("manual-")
    assert item["integrity"] == "ok"
    assert item["restorable"] is True
    assert item["dump_major"] == 16

    download = await client.get(
        f"/api/v1/admin/backups/{item['name']}/download", headers=headers(admin)
    )
    assert download.status_code == 200
    assert download.content[:5] == b"PGDMP"

    deleted = await client.delete(f"/api/v1/admin/backups/{item['name']}", headers=headers(admin))
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/admin/backups", headers=headers(admin))).json()["items"] == []
    assert await audit_actions(admin) == [
        AdminAction.backup_created,
        AdminAction.backup_downloaded,
        AdminAction.backup_deleted,
    ]


async def test_create_fails_visibly_when_dump_tool_fails(
    client: AsyncClient, admin: User, monkeypatch: pytest.MonkeyPatch
):
    async def broken(*args, **kwargs):
        return 1, "", "connection refused"

    monkeypatch.setattr(admin_backups, "run", broken)

    await client.post("/api/v1/admin/backups", headers=headers(admin))
    job = await wait_for_job(client, admin)

    assert job["state"] == "failed"
    assert "connection refused" in job["message"]
    assert await audit_actions(admin) == [AdminAction.backup_create_failed]
    assert await Redis.from_url(get_settings().redis_url).get(admin_backups.LOCK_KEY) is None


async def test_second_operation_is_refused_while_busy(client: AsyncClient, admin: User):
    await admin_backups.start_job("create", None)

    response = await client.post("/api/v1/admin/backups", headers=headers(admin))

    assert response.status_code == 409
    assert response.json()["detail"] == admin_backups.BUSY


async def test_download_and_restore_reject_bad_names_and_symlinks(
    client: AsyncClient, admin: User, clean_state: Path, tmp_path: Path
):
    secret = tmp_path / "secret.dump"
    secret.write_bytes(b"PGDMPsecret")
    os.symlink(secret, clean_state / "lecturo-link.dump")

    for name in ("..%2Fsecret.dump", "lecturo-link.dump", "missing.dump", "x.sql"):
        response = await client.get(
            f"/api/v1/admin/backups/{name}/download", headers=headers(admin)
        )
        assert response.status_code in (404, 422), name
    listing = await client.get("/api/v1/admin/backups", headers=headers(admin))
    assert listing.json()["items"] == []


async def test_upload_rejects_non_dump_and_leaves_no_files(
    client: AsyncClient, admin: User, clean_state: Path
):
    response = await client.post(
        "/api/v1/admin/backups/upload",
        headers=headers(admin),
        content=b"-- plain sql\nDROP TABLE users;\n",
    )

    assert response.status_code == 422
    assert response.json()["detail"] == admin_backups.NOT_A_DUMP
    assert names(clean_state) == []
    assert await audit_actions(admin) == [AdminAction.backup_upload_rejected]


async def test_upload_rejects_too_large_file(
    client: AsyncClient, admin: User, clean_state: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(get_settings(), "backup_max_upload_mb", 1)

    response = await client.post(
        "/api/v1/admin/backups/upload",
        headers=headers(admin),
        content=b"PGDMP" + secrets.token_bytes(2 * 1024 * 1024),
    )

    assert response.status_code == 413
    assert names(clean_state) == []


@needs_postgres_tools
async def test_upload_rejects_broken_dump(client: AsyncClient, admin: User, clean_state: Path):
    response = await client.post(
        "/api/v1/admin/backups/upload",
        headers=headers(admin),
        content=b"PGDMP" + secrets.token_bytes(4096),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == admin_backups.BROKEN_DUMP
    assert names(clean_state) == []


@needs_postgres_tools
async def test_upload_accepts_valid_dump_without_applying_it(
    client: AsyncClient, admin: User, clean_state: Path
):
    source = await make_dump(clean_state)
    content = source.read_bytes()
    source.unlink()

    response = await client.post(
        "/api/v1/admin/backups/upload", headers=headers(admin), content=content
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"].startswith("uploaded-")
    assert body["integrity"] == "ok"
    assert (clean_state / body["name"]).read_bytes() == content
    assert await Redis.from_url(get_settings().redis_url).get(maintenance.MAINTENANCE_KEY) is None
    assert await audit_actions(admin) == [AdminAction.backup_uploaded]


@needs_postgres_tools
async def test_restore_is_refused_without_confirmations(
    client: AsyncClient, admin: User, clean_state: Path
):
    path = await make_dump(clean_state)
    url = f"/api/v1/admin/backups/{path.name}/restore"

    no_word = await client.post(
        url, headers=headers(admin), json={"password": PASSWORD, "confirmation": "restore"}
    )
    wrong_password = await client.post(
        url, headers=headers(admin), json={"password": "не тот пароль", "confirmation": "RESTORE"}
    )
    missing_body = await client.post(url, headers=headers(admin), json={})

    assert no_word.status_code == 403
    assert no_word.json()["detail"] == admin_backups.WRONG_WORD
    assert wrong_password.status_code == 403
    assert wrong_password.json()["detail"] == admin_backups.WRONG_PASSWORD
    assert missing_body.status_code == 422
    assert await admin_backups.read_job() is None
    assert not await maintenance.is_active(use_cache=False)
    assert await audit_actions(admin) == [AdminAction.restore_denied, AdminAction.restore_denied]


@needs_postgres_tools
async def test_restore_attempts_are_rate_limited(
    client: AsyncClient, admin: User, clean_state: Path
):
    path = await make_dump(clean_state)
    url = f"/api/v1/admin/backups/{path.name}/restore"
    body = {"password": "не тот", "confirmation": "RESTORE"}

    codes = [
        (await client.post(url, headers=headers(admin), json=body)).status_code for _ in range(7)
    ]
    right = await client.post(
        url, headers=headers(admin), json={"password": PASSWORD, "confirmation": "RESTORE"}
    )
    await Redis.from_url(get_settings().redis_url).delete(f"rate:admin-restore:{admin.id}")

    assert codes[:5] == [403] * 5
    assert codes[5:] == [429, 429]
    assert right.status_code == 429
    assert await admin_backups.read_job() is None


async def test_restore_needs_admin_password(client: AsyncClient, admin: User, clean_state: Path):
    async with SessionLocal() as session:
        stored = await session.get(User, admin.id)
        stored.password_hash = None
        await session.commit()
    (clean_state / "lecturo-1.dump").write_bytes(b"PGDMP")

    response = await client.post(
        "/api/v1/admin/backups/lecturo-1.dump/restore",
        headers=headers(admin),
        json={"password": PASSWORD, "confirmation": "RESTORE"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == admin_backups.NO_PASSWORD


async def test_encrypted_archive_cannot_be_restored(
    client: AsyncClient, admin: User, clean_state: Path
):
    (clean_state / "lecturo-1.tar.age").write_bytes(b"age-encryption.org/v1")

    listing = await client.get("/api/v1/admin/backups", headers=headers(admin))
    response = await client.post(
        "/api/v1/admin/backups/lecturo-1.tar.age/restore",
        headers=headers(admin),
        json={"password": PASSWORD, "confirmation": "RESTORE"},
    )

    assert listing.json()["items"][0]["integrity"] == "encrypted"
    assert listing.json()["items"][0]["restorable"] is False
    assert response.status_code == 422


def scratch_target(name: str) -> admin_backups.DatabaseTarget:
    base = admin_backups.database_target()
    return admin_backups.DatabaseTarget(base.host, base.port, base.user, base.password, name)


@pytest.fixture
async def scratch_database() -> AsyncIterator[admin_backups.DatabaseTarget]:
    name = f"lecturo_scratch_{secrets.token_hex(4)}"
    target = scratch_target(name)
    await admin_backups.psql(
        target, admin_backups.MAINTENANCE_DATABASE, f'CREATE DATABASE "{name}"'
    )
    yield target
    await admin_backups.psql(
        target, admin_backups.MAINTENANCE_DATABASE, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'
    )


async def run_restore_job(admin: User, path: Path, target: admin_backups.DatabaseTarget) -> dict:
    job = await admin_backups.start_job("restore", path.name)
    resumed: list[bool] = []

    async def resume() -> None:
        resumed.append(True)

    await admin_backups.run_restore(job, path, admin.id, admin.email, target, resume)
    job["resumed"] = bool(resumed)
    return job


@needs_postgres_tools
async def test_restore_replaces_database_with_maintenance_and_safety_dump(
    admin: User, clean_state: Path, scratch_database: admin_backups.DatabaseTarget, monkeypatch
):
    source = await make_dump(clean_state)
    await admin_backups.psql(
        scratch_database, scratch_database.database, "CREATE TABLE leftover (id int)"
    )
    seen: list[bool] = []
    original = admin_backups.trial_restore

    async def observing(path: Path, target: admin_backups.DatabaseTarget) -> str:
        seen.append(await maintenance.is_active(use_cache=False))
        return await original(path, target)

    monkeypatch.setattr(admin_backups, "trial_restore", observing)

    job = await run_restore_job(admin, source, scratch_database)

    assert job["state"] == "done"
    assert job["resumed"] is True
    assert seen == [True]
    assert not await maintenance.is_active(use_cache=False)
    tables = await admin_backups.psql(
        scratch_database,
        scratch_database.database,
        "SELECT count(*) FILTER (WHERE table_name = 'users') || ',' "
        "|| count(*) FILTER (WHERE table_name = 'leftover') "
        "FROM information_schema.tables WHERE table_schema = 'public'",
    )
    assert tables == "1,0"
    assert len(names(clean_state, "pre-restore-*.dump")) == 1
    assert AdminAction.restore_finished in await audit_actions(admin)


@needs_postgres_tools
async def test_restore_of_broken_dump_keeps_database_and_ends_maintenance(
    admin: User, clean_state: Path, scratch_database: admin_backups.DatabaseTarget
):
    await admin_backups.psql(
        scratch_database, scratch_database.database, "CREATE TABLE keepme (id int)"
    )
    source = await make_dump(clean_state)
    damaged = clean_state / "lecturo-damaged.dump"
    damaged.write_bytes(source.read_bytes()[: source.stat().st_size // 2])

    job = await run_restore_job(admin, damaged, scratch_database)

    assert job["state"] == "failed"
    assert not await maintenance.is_active(use_cache=False)
    kept = await admin_backups.psql(
        scratch_database, scratch_database.database, "SELECT count(*) FROM keepme"
    )
    assert kept == "0"
    assert AdminAction.restore_failed in await audit_actions(admin)
    assert await Redis.from_url(get_settings().redis_url).get(admin_backups.LOCK_KEY) is None


@needs_postgres_tools
async def test_failed_restore_after_drop_rolls_back_to_safety_dump(
    admin: User,
    clean_state: Path,
    scratch_database: admin_backups.DatabaseTarget,
    monkeypatch: pytest.MonkeyPatch,
):
    await admin_backups.psql(
        scratch_database, scratch_database.database, "CREATE TABLE keepme (id int)"
    )
    source = await make_dump(clean_state)
    original = admin_backups.replace_database
    calls: list[str] = []

    async def failing_first(path: Path, target: admin_backups.DatabaseTarget) -> None:
        calls.append(path.name)
        if len(calls) == 1:
            await original(path, target)
            raise admin_backups.BackupError("сбой после восстановления")
        await original(path, target)

    monkeypatch.setattr(admin_backups, "replace_database", failing_first)

    job = await run_restore_job(admin, source, scratch_database)

    assert job["state"] == "failed"
    assert "Прежняя база возвращена" in job["message"]
    assert calls[1].startswith("pre-restore-")
    assert not await maintenance.is_active(use_cache=False)
    kept = await admin_backups.psql(
        scratch_database, scratch_database.database, "SELECT count(*) FROM keepme"
    )
    assert kept == "0"


@needs_postgres_tools
async def test_restore_waits_for_running_jobs_and_gives_up(
    admin: User,
    clean_state: Path,
    scratch_database: admin_backups.DatabaseTarget,
    monkeypatch: pytest.MonkeyPatch,
):
    source = await make_dump(clean_state)
    monkeypatch.setattr(get_settings(), "restore_idle_wait_seconds", 0)
    redis = Redis.from_url(get_settings().redis_url)
    await redis.set("arq:in-progress:lecture:test", "1", ex=60)

    job = await run_restore_job(admin, source, scratch_database)
    await redis.delete("arq:in-progress:lecture:test")
    await redis.aclose()

    assert job["state"] == "failed"
    assert job["message"] == admin_backups.ACTIVE_JOBS
    assert not names(clean_state, "pre-restore-*.dump")
    assert not await maintenance.is_active(use_cache=False)


async def test_maintenance_blocks_site_but_not_health_or_admin(client: AsyncClient, admin: User):
    await maintenance.enable("restore")
    try:
        blocked = await client.get("/api/v1/billing/products")
        health = await client.get("/api/v1/health")
        flag = await client.get("/api/v1/maintenance")
        panel = await client.get("/api/v1/admin/backups", headers=headers(admin))
    finally:
        await maintenance.disable()
    reopened = await client.get("/api/v1/billing/products")

    assert blocked.status_code == 503
    assert blocked.json()["maintenance"] is True
    assert blocked.headers["retry-after"] == "30"
    assert health.status_code == 200
    assert flag.json() == {"active": True, "message": maintenance.MAINTENANCE_MESSAGE}
    assert panel.status_code == 200
    assert panel.json()["maintenance"] is True
    assert reopened.status_code == 200


async def test_worker_jobs_wait_while_maintenance_is_on():
    await maintenance.enable("restore")
    try:
        with pytest.raises(Retry) as retry:
            await process_lecture({}, str(uuid.uuid4()))
    finally:
        await maintenance.disable()

    assert retry.value.defer_score == maintenance.JOB_DEFER_SECONDS * 1000


async def test_admin_can_end_stuck_maintenance(client: AsyncClient, admin: User):
    await maintenance.enable("restore")

    response = await client.post("/api/v1/admin/maintenance/disable", headers=headers(admin))

    assert response.status_code == 204
    assert not await maintenance.is_active(use_cache=False)
    assert await audit_actions(admin) == [AdminAction.maintenance_disabled]


async def test_interrupted_restore_is_marked_failed_on_start(admin: User):
    await admin_backups.start_job("restore", "lecturo-1.dump")
    await maintenance.enable("restore")

    await admin_backups.mark_interrupted_job()

    job = await admin_backups.read_job()
    assert job["state"] == "failed"
    assert job["message"] == admin_backups.INTERRUPTED
    assert await maintenance.is_active(use_cache=False)
