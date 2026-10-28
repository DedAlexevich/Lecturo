import asyncio
import json
import logging
import os
import re
import secrets
import stat
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from arq import create_pool
from arq.constants import in_progress_key_prefix
from redis.exceptions import RedisError
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.core.redis import get_redis
from app.models import AdminAction, User
from app.services import maintenance
from app.services.admin import record_action, user_label
from app.services.admin_logs import mask_text

logger = logging.getLogger(__name__)

BACKUP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.(dump|tar\.age)$")
DUMP_MAGIC = b"PGDMP"
MAINTENANCE_DATABASE = "postgres"
JOB_KEY = "lecturo:backup:job"
LOCK_KEY = "lecturo:backup:lock"
LOCK_SECONDS = 2 * 3600
JOB_TTL_SECONDS = 7 * 24 * 3600
COMMAND_TIMEOUT_SECONDS = 3600
CHECK_TIMEOUT_SECONDS = 120
KEEP_PRE_RESTORE = 3
RESTORE_WORD = "RESTORE"
UPLOAD_CHUNK = 1024 * 1024

NOT_FOUND = "Бэкап не найден"
BAD_NAME = "Недопустимое имя файла бэкапа"
ENCRYPTED_NOT_RESTORABLE = "Зашифрованный архив нельзя восстановить из панели"
BUSY = "Уже выполняется другая операция с бэкапами"
NOT_A_DUMP = "Файл не похож на дамп PostgreSQL (формат custom)"
TOO_LARGE = "Файл больше допустимого размера"
BROKEN_DUMP = "Дамп повреждён: pg_restore не смог прочитать оглавление"
NEWER_DUMP = "Дамп сделан более новой версией PostgreSQL, чем на сервере"
NEWER_SCHEMA = "Дамп содержит схему базы новее, чем у приложения"
NO_DISK = "Не хватает места в папке бэкапов"
NO_PASSWORD = "У аккаунта нет пароля: задайте пароль в настройках, чтобы подтвердить восстановление"
WRONG_PASSWORD = "Неверный пароль"
WRONG_WORD = "Нужно ввести слово RESTORE"
ACTIVE_JOBS = "Идёт обработка лекций, дождитесь её завершения и повторите"
INTERRUPTED = "Операция прервана перезапуском сервера"


class BackupError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class DatabaseTarget:
    host: str
    port: int
    user: str
    password: str
    database: str

    def env(self, database: str | None = None) -> dict[str, str]:
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PGHOST": self.host,
            "PGPORT": str(self.port),
            "PGUSER": self.user,
            "PGPASSWORD": self.password,
            "PGDATABASE": database or self.database,
        }


def database_target() -> DatabaseTarget:
    url = make_url(get_settings().database_url)
    return DatabaseTarget(
        host=url.host or "localhost",
        port=url.port or 5432,
        user=url.username or "",
        password=url.password or "",
        database=url.database or "",
    )


@dataclass
class DumpInfo:
    ok: bool
    error: str | None = None
    dump_major: int | None = None


@dataclass
class BackupFile:
    name: str
    size: int
    modified_at: datetime
    encrypted: bool
    source: str


def backup_dir() -> Path:
    return get_settings().backup_dir


def validate_name(name: str) -> str:
    if not BACKUP_NAME.fullmatch(name) or ".." in name:
        raise BackupError(BAD_NAME)
    return name


def source_of(name: str) -> str:
    for prefix in ("lecturo", "manual", "uploaded", "pre-restore"):
        if name.startswith(f"{prefix}-"):
            return prefix
    return "other"


def backup_file(name: str) -> Path:
    validate_name(name)
    path = backup_dir() / name
    try:
        info = path.lstat()
    except OSError as error:
        raise BackupError(NOT_FOUND) from error
    if not stat.S_ISREG(info.st_mode):
        raise BackupError(NOT_FOUND)
    return path


def list_backups_sync() -> list[BackupFile]:
    directory = backup_dir()
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    files = []
    for entry in entries:
        if entry.name.startswith(".") or not BACKUP_NAME.fullmatch(entry.name):
            continue
        try:
            info = entry.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        files.append(
            BackupFile(
                name=entry.name,
                size=info.st_size,
                modified_at=datetime.fromtimestamp(info.st_mtime, UTC),
                encrypted=entry.name.endswith(".tar.age"),
                source=source_of(entry.name),
            )
        )
    return sorted(files, key=lambda item: item.modified_at, reverse=True)


async def list_backups() -> list[BackupFile]:
    return await asyncio.to_thread(list_backups_sync)


async def run(
    command: list[str],
    env: dict[str, str],
    timeout_seconds: float,
    stdout_path: Path | None = None,
    stdin_path: Path | None = None,
) -> tuple[int, str, str]:
    stdout = None
    stdin = None
    try:
        if stdout_path is not None:
            stdout = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        if stdin_path is not None:
            stdin = os.open(stdin_path, os.O_RDONLY)
        process = await asyncio.create_subprocess_exec(
            *command,
            env=env,
            stdin=stdin if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=stdout if stdout is not None else asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(), timeout_seconds)
        except TimeoutError:
            process.kill()
            await process.wait()
            return 124, "", "timeout"
    finally:
        for descriptor in (stdout, stdin):
            if descriptor is not None:
                os.close(descriptor)
    return (
        process.returncode or 0,
        (out or b"").decode(errors="replace"),
        mask_text((err or b"").decode(errors="replace")).strip(),
    )


async def psql(target: DatabaseTarget, database: str, sql: str) -> str:
    code, out, err = await run(
        ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-Atc", sql],
        target.env(database),
        CHECK_TIMEOUT_SECONDS,
    )
    if code != 0:
        raise BackupError(f"psql: {err[-500:]}")
    return out.strip()


def major_of(version: str) -> int | None:
    found = re.match(r"\s*(\d+)", version)
    return int(found.group(1)) if found else None


def parse_listing(listing: str) -> DumpInfo:
    dump_major = None
    for line in listing.splitlines():
        if not line.startswith(";"):
            break
        key, _, value = line[1:].partition(":")
        if key.strip() == "Dumped from database version":
            dump_major = major_of(value)
    return DumpInfo(ok=True, dump_major=dump_major)


async def server_major(target: DatabaseTarget) -> int | None:
    value = await psql(target, MAINTENANCE_DATABASE, "SHOW server_version_num")
    return int(value) // 10000 if value.isdigit() else None


async def inspect_dump(path: Path) -> DumpInfo:
    code, out, err = await run(
        ["pg_restore", "--list", str(path)],
        {"PATH": os.environ.get("PATH", "")},
        CHECK_TIMEOUT_SECONDS,
    )
    if code != 0:
        return DumpInfo(ok=False, error=BROKEN_DUMP)
    return parse_listing(out)


integrity_cache: dict[tuple[str, int, int], DumpInfo] = {}


async def check_integrity(name: str) -> DumpInfo | None:
    if name.endswith(".tar.age"):
        return None
    path = backup_file(name)
    info = path.lstat()
    key = (name, info.st_size, info.st_mtime_ns)
    cached = integrity_cache.get(key)
    if cached is None:
        cached = await inspect_dump(path)
        if len(integrity_cache) > 200:
            integrity_cache.clear()
        integrity_cache[key] = cached
    return cached


def check_dump_version(info: DumpInfo, server: int | None) -> None:
    if info.dump_major is not None and server is not None and info.dump_major > server:
        raise BackupError(NEWER_DUMP)


BACKEND_DIR = Path(__file__).resolve().parents[2]


def head_revision() -> str | None:
    return script_directory().get_current_head()


def script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config)


def check_schema_known(revision: str) -> bool:
    try:
        return script_directory().get_revision(revision) is not None
    except Exception:
        return False


def timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


async def dump_to(path: Path, target: DatabaseTarget) -> None:
    part = path.with_name(f".{path.name}.part")
    try:
        code, _, err = await run(
            ["pg_dump", "-Fc", "-d", target.database],
            target.env(),
            COMMAND_TIMEOUT_SECONDS,
            stdout_path=part,
        )
        if code != 0:
            raise BackupError(f"pg_dump завершился с ошибкой: {err[-500:]}")
        info = await inspect_dump(part)
        if not info.ok:
            raise BackupError(BROKEN_DUMP)
        os.replace(part, path)
    except OSError as error:
        raise BackupError(NO_DISK) from error
    finally:
        part.unlink(missing_ok=True)


async def create_dump(prefix: str = "manual") -> Path:
    path = backup_dir() / f"{prefix}-{timestamp()}.dump"
    backup_dir().mkdir(parents=True, exist_ok=True)
    await dump_to(path, database_target())
    return path


def rotate_pre_restore() -> None:
    old = sorted(backup_dir().glob("pre-restore-*.dump"), reverse=True)[KEEP_PRE_RESTORE:]
    for path in old:
        path.unlink(missing_ok=True)


def delete_backup(name: str) -> None:
    if source_of(name) == "lecturo":
        raise BackupError("Плановые бэкапы удаляет ротация, вручную их не удаляют")
    backup_file(name).unlink(missing_ok=True)
    integrity_cache.clear()


async def save_upload(stream: AsyncIterator[bytes]) -> tuple[Path, DumpInfo]:
    limit = get_settings().backup_max_upload_mb * 1024 * 1024
    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    part = directory / f".upload-{secrets.token_hex(8)}.part"
    written = 0
    first = b""
    try:
        descriptor = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            async for chunk in stream:
                if len(first) < len(DUMP_MAGIC):
                    first = (first + chunk)[: len(DUMP_MAGIC)]
                written += len(chunk)
                if written > limit:
                    raise BackupError(TOO_LARGE)
                await asyncio.to_thread(handle.write, chunk)
        if first != DUMP_MAGIC:
            raise BackupError(NOT_A_DUMP)
        info = await inspect_dump(part)
        if not info.ok:
            raise BackupError(info.error or BROKEN_DUMP)
        check_dump_version(info, await server_major(database_target()))
        final = directory / f"uploaded-{timestamp()}.dump"
        os.replace(part, final)
    except OSError as error:
        raise BackupError(NO_DISK) from error
    finally:
        part.unlink(missing_ok=True)
    integrity_cache.clear()
    return final, info


async def read_job() -> dict | None:
    raw = await get_redis(get_settings().redis_url).get(JOB_KEY)
    return json.loads(raw) if raw else None


async def write_job(job: dict) -> None:
    await get_redis(get_settings().redis_url).set(JOB_KEY, json.dumps(job), ex=JOB_TTL_SECONDS)


async def acquire_lock(owner: str) -> bool:
    return bool(
        await get_redis(get_settings().redis_url).set(LOCK_KEY, owner, nx=True, ex=LOCK_SECONDS)
    )


async def release_lock(owner: str) -> None:
    redis = get_redis(get_settings().redis_url)
    if (await redis.get(LOCK_KEY) or b"").decode() == owner:
        await redis.delete(LOCK_KEY)


async def start_job(kind: str, backup: str | None) -> dict:
    job_id = uuid.uuid4().hex
    if not await acquire_lock(job_id):
        raise BackupError(BUSY)
    job = {
        "id": job_id,
        "kind": kind,
        "state": "running",
        "step": "start",
        "message": "",
        "backup": backup,
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
    }
    await write_job(job)
    return job


async def update_job(job: dict, **changes: object) -> None:
    job.update(changes)
    if job["state"] != "running":
        job["finished_at"] = datetime.now(UTC).isoformat()
    await write_job(job)


background: set[asyncio.Task] = set()


def spawn(coroutine: Awaitable[None]) -> None:
    task = asyncio.ensure_future(coroutine)
    background.add(task)
    task.add_done_callback(background.discard)


async def audit(
    actor_id: uuid.UUID | None,
    actor_label: str,
    action: AdminAction,
    name: str | None,
    details: dict,
) -> None:
    async with SessionLocal() as session:
        actor = await session.get(User, actor_id) if actor_id else None
        record_action(
            session,
            actor,
            action,
            "backup",
            name,
            name or "",
            {**details, **({} if actor else {"actor": actor_label})},
        )
        await session.commit()


async def run_create(job: dict, actor_id: uuid.UUID, actor: str) -> None:
    path: Path | None = None
    problem = ""
    try:
        await update_job(job, step="dump")
        path = await create_dump("manual")
    except BackupError as error:
        problem = error.message
    except Exception:
        logger.exception("Не удалось создать дамп")
        problem = "Не удалось создать дамп, подробности в логе api"
    try:
        if path is not None:
            size = path.stat().st_size
            await audit(actor_id, actor, AdminAction.backup_created, path.name, {"size": size})
            await update_job(job, state="done", step="finished", backup=path.name)
        else:
            await audit(actor_id, actor, AdminAction.backup_create_failed, None, {"error": problem})
            await update_job(job, state="failed", message=problem)
    finally:
        await release_lock(job["id"])


async def wait_for_idle_workers(wait_seconds: int) -> bool:
    redis = get_redis(get_settings().redis_url)
    deadline = time.monotonic() + wait_seconds
    while True:
        busy = False
        async for _ in redis.scan_iter(match=f"{in_progress_key_prefix}*", count=100):
            busy = True
            break
        if not busy:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(3)


async def trial_restore(path: Path, target: DatabaseTarget) -> str:
    name = f"lecturo_check_{secrets.token_hex(4)}"
    await psql(target, MAINTENANCE_DATABASE, f'CREATE DATABASE "{name}"')
    try:
        code, _, err = await run(
            ["pg_restore", "-d", name, "--no-owner", "--exit-on-error", str(path)],
            target.env(name),
            COMMAND_TIMEOUT_SECONDS,
        )
        if code != 0:
            raise BackupError(f"Тестовое восстановление не удалось: {err[-500:]}")
        revision = await psql(target, name, "SELECT version_num FROM alembic_version")
        if not revision:
            raise BackupError("В дампе нет версии схемы alembic_version")
        if not check_schema_known(revision):
            raise BackupError(NEWER_SCHEMA)
        return revision
    finally:
        await psql(target, MAINTENANCE_DATABASE, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


async def replace_database(path: Path, target: DatabaseTarget) -> None:
    await engine.dispose()
    await psql(
        target, MAINTENANCE_DATABASE, f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'
    )
    await psql(target, MAINTENANCE_DATABASE, f'CREATE DATABASE "{target.database}"')
    code, _, err = await run(
        ["pg_restore", "-d", target.database, "--no-owner", "--exit-on-error", str(path)],
        target.env(),
        COMMAND_TIMEOUT_SECONDS,
    )
    if code != 0:
        raise BackupError(f"pg_restore завершился с ошибкой: {err[-500:]}")


async def upgrade_schema() -> None:
    process = await asyncio.create_subprocess_exec(
        "python",
        "-m",
        "alembic",
        "upgrade",
        "head",
        cwd=BACKEND_DIR,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await process.communicate()
    if process.returncode != 0:
        raise BackupError(f"alembic upgrade head не выполнен: {mask_text(err.decode())[-500:]}")


async def resume_lectures() -> None:
    from app.pipeline.tasks import queue_settings, resume_interrupted_lectures

    redis = await create_pool(queue_settings())
    try:
        await resume_interrupted_lectures(redis)
    finally:
        await redis.aclose()


async def run_restore(
    job: dict,
    path: Path,
    actor_id: uuid.UUID,
    actor: str,
    target: DatabaseTarget,
    resume: Callable[[], Awaitable[None]] = resume_lectures,
) -> None:
    name = path.name
    safety: Path | None = None
    replaced = False
    try:
        await update_job(job, step="maintenance")
        await maintenance.enable("restore")
        await update_job(job, step="waiting_workers")
        if not await wait_for_idle_workers(get_settings().restore_idle_wait_seconds):
            raise BackupError(ACTIVE_JOBS)
        await update_job(job, step="pre_restore_dump")
        safety = backup_dir() / f"pre-restore-{timestamp()}.dump"
        await dump_to(safety, target)
        await update_job(job, step="test_restore")
        revision = await trial_restore(path, target)
        await update_job(job, step="restore")
        replaced = True
        await replace_database(path, target)
        if revision != head_revision():
            await update_job(job, step="migrate")
            await upgrade_schema()
        await engine.dispose()
        rotate_pre_restore()
        await audit(
            actor_id,
            actor,
            AdminAction.restore_finished,
            name,
            {"schema_revision": revision, "pre_restore": safety.name},
        )
        await update_job(job, step="resume")
        await resume()
        await maintenance.disable()
        await update_job(job, state="done", step="finished")
    except BackupError as error:
        await fail_restore(
            job, error.message, safety if replaced else None, target, actor_id, actor, name
        )
    except Exception:
        logger.exception("Восстановление из %s не удалось", name)
        await fail_restore(
            job,
            "Восстановление не удалось, подробности в логе api",
            safety if replaced else None,
            target,
            actor_id,
            actor,
            name,
        )
    finally:
        await release_lock(job["id"])


async def fail_restore(
    job: dict,
    message: str,
    rollback: Path | None,
    target: DatabaseTarget,
    actor_id: uuid.UUID,
    actor: str,
    name: str,
) -> None:
    rolled_back = rollback is None
    if rollback is not None:
        try:
            await replace_database(rollback, target)
            rolled_back = True
        except Exception:
            logger.exception("Не удалось вернуть базу из %s", rollback.name)
    if rolled_back:
        await engine.dispose()
        await maintenance.disable()
        suffix = " Прежняя база возвращена." if rollback is not None else ""
        note = message + suffix
    else:
        note = (
            f"{message} Прежнюю базу вернуть не удалось, сайт остаётся в режиме обслуживания, "
            f"дамп перед восстановлением: {rollback.name}."
        )
    try:
        await audit(actor_id, actor, AdminAction.restore_failed, name, {"error": note})
    except Exception:
        logger.exception("Не удалось записать отказ восстановления в журнал")
    await update_job(job, state="failed", message=note)


async def start_create(actor: User) -> dict:
    job = await start_job("create", None)
    spawn(run_create(job, actor.id, user_label(actor)))
    return job


async def start_restore(actor: User, path: Path) -> dict:
    job = await start_job("restore", path.name)
    spawn(run_restore(job, path, actor.id, user_label(actor), database_target()))
    return job


async def mark_interrupted_job() -> None:
    try:
        job = await read_job()
        if job is None or job["state"] != "running":
            return
        await update_job(job, state="failed", message=INTERRUPTED)
        await get_redis(get_settings().redis_url).delete(LOCK_KEY)
    except (OSError, RedisError):
        logger.warning("Не удалось проверить прерванную операцию с бэкапами")
