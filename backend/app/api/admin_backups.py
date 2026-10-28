import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.deps import AdminUser, SessionDep, get_admin_user
from app.models import AdminAction
from app.schemas.admin_backups import (
    BackupIntegrity,
    BackupJobOut,
    BackupOut,
    BackupsOut,
    RestoreIn,
)
from app.services import admin_backups, maintenance
from app.services.admin import record_action
from app.services.auth import verify_password
from app.services.rate_limit import count_failure, ensure_below_limit

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_admin_user)])

INTEGRITY_PARALLEL = 3
RESTORE_ATTEMPTS = 5
RESTORE_WINDOW_SECONDS = 900
NOT_FOUND_RESPONSE = {status.HTTP_404_NOT_FOUND: {"description": admin_backups.NOT_FOUND}}


def fail(error: admin_backups.BackupError) -> HTTPException:
    if error.message == admin_backups.NOT_FOUND:
        code = status.HTTP_404_NOT_FOUND
    elif error.message == admin_backups.BUSY:
        code = status.HTTP_409_CONFLICT
    else:
        code = 422
    return HTTPException(code, error.message)


async def describe(item: admin_backups.BackupFile) -> BackupOut:
    if item.encrypted:
        integrity, major = BackupIntegrity.encrypted, None
    else:
        info = await admin_backups.check_integrity(item.name)
        integrity = BackupIntegrity.ok if info and info.ok else BackupIntegrity.broken
        major = info.dump_major if info else None
    return BackupOut(
        name=item.name,
        size=item.size,
        modified_at=item.modified_at,
        source=item.source,
        integrity=integrity,
        dump_major=major,
        restorable=integrity == BackupIntegrity.ok,
    )


async def current_job() -> BackupJobOut | None:
    job = await admin_backups.read_job()
    return BackupJobOut(**job) if job else None


@router.get("/backups")
async def get_backups() -> BackupsOut:
    files = await admin_backups.list_backups()
    gate = asyncio.Semaphore(INTEGRITY_PARALLEL)

    async def limited(item: admin_backups.BackupFile) -> BackupOut:
        async with gate:
            return await describe(item)

    return BackupsOut(
        items=list(await asyncio.gather(*(limited(item) for item in files))),
        job=await current_job(),
        maintenance=await maintenance.is_active(use_cache=False),
    )


@router.get("/backups/job")
async def get_backup_job() -> BackupJobOut | None:
    return await current_job()


@router.post(
    "/backups",
    status_code=status.HTTP_202_ACCEPTED,
    responses={status.HTTP_409_CONFLICT: {"description": admin_backups.BUSY}},
)
async def create_backup(actor: AdminUser) -> BackupJobOut:
    try:
        job = await admin_backups.start_create(actor)
    except admin_backups.BackupError as error:
        raise fail(error) from error
    return BackupJobOut(**job)


@router.post(
    "/backups/upload",
    status_code=status.HTTP_201_CREATED,
    responses={
        413: {"description": admin_backups.TOO_LARGE},
        422: {"description": admin_backups.NOT_A_DUMP},
    },
)
async def upload_backup(request: Request, actor: AdminUser, session: SessionDep) -> BackupOut:
    limit = get_settings().backup_max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, admin_backups.TOO_LARGE)
    try:
        path, info = await admin_backups.save_upload(request.stream())
    except admin_backups.BackupError as error:
        record_action(
            session,
            actor,
            AdminAction.backup_upload_rejected,
            "backup",
            None,
            "",
            {"error": error.message},
        )
        await session.commit()
        if error.message == admin_backups.TOO_LARGE:
            code = 413
        else:
            code = 422
        raise HTTPException(code, error.message) from error
    record_action(
        session,
        actor,
        AdminAction.backup_uploaded,
        "backup",
        path.name,
        path.name,
        {"size": path.stat().st_size, "dump_major": info.dump_major},
    )
    await session.commit()
    files = await admin_backups.list_backups()
    return await describe(next(item for item in files if item.name == path.name))


@router.get("/backups/{name}/download", responses=NOT_FOUND_RESPONSE)
async def download_backup(name: str, actor: AdminUser, session: SessionDep) -> FileResponse:
    try:
        path = admin_backups.backup_file(name)
    except admin_backups.BackupError as error:
        raise fail(error) from error
    record_action(
        session,
        actor,
        AdminAction.backup_downloaded,
        "backup",
        name,
        name,
        {"size": path.stat().st_size},
    )
    await session.commit()
    return FileResponse(path, media_type="application/octet-stream", filename=name)


@router.delete(
    "/backups/{name}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND_RESPONSE
)
async def delete_backup(name: str, actor: AdminUser, session: SessionDep) -> None:
    try:
        admin_backups.delete_backup(name)
    except admin_backups.BackupError as error:
        raise fail(error) from error
    record_action(session, actor, AdminAction.backup_deleted, "backup", name, name)
    await session.commit()


@router.post(
    "/backups/{name}/restore",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **NOT_FOUND_RESPONSE,
        status.HTTP_403_FORBIDDEN: {"description": admin_backups.WRONG_PASSWORD},
        status.HTTP_409_CONFLICT: {"description": admin_backups.BUSY},
    },
)
async def restore_backup(
    name: str, body: RestoreIn, actor: AdminUser, session: SessionDep
) -> BackupJobOut:
    try:
        path = admin_backups.backup_file(name)
    except admin_backups.BackupError as error:
        raise fail(error) from error
    if name.endswith(".tar.age"):
        raise HTTPException(422, admin_backups.ENCRYPTED_NOT_RESTORABLE)
    if not actor.password_hash:
        raise HTTPException(422, admin_backups.NO_PASSWORD)
    redis_url = get_settings().redis_url
    attempts_key = f"rate:admin-restore:{actor.id}"
    await ensure_below_limit(redis_url, attempts_key, RESTORE_ATTEMPTS)
    denial = None
    if body.confirmation != admin_backups.RESTORE_WORD:
        denial = admin_backups.WRONG_WORD
    elif not verify_password(actor.password_hash, body.password):
        denial = admin_backups.WRONG_PASSWORD
    if denial is not None:
        await count_failure(redis_url, attempts_key, RESTORE_WINDOW_SECONDS)
        record_action(
            session, actor, AdminAction.restore_denied, "backup", name, name, {"reason": denial}
        )
        await session.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, denial)
    info = await admin_backups.inspect_dump(path)
    if not info.ok:
        raise HTTPException(422, info.error)
    try:
        server = await admin_backups.server_major(admin_backups.database_target())
        admin_backups.check_dump_version(info, server)
        job = await admin_backups.start_restore(actor, path)
    except admin_backups.BackupError as error:
        raise fail(error) from error
    record_action(
        session,
        actor,
        AdminAction.restore_started,
        "backup",
        name,
        name,
        {"dump_major": info.dump_major},
    )
    await session.commit()
    return BackupJobOut(**job)


@router.post("/maintenance/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_maintenance(actor: AdminUser, session: SessionDep) -> None:
    await maintenance.disable()
    record_action(session, actor, AdminAction.maintenance_disabled, "maintenance", None)
    await session.commit()
