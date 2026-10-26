import asyncio
import json
import logging
import re
import secrets
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_pascal
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.courses import get_own_course
from app.api.lectures import add_to_course
from app.core.config import get_settings
from app.core.deps import SessionDep
from app.core.security import decode_access_token
from app.models import Lecture, LectureStatus, SourceType, User
from app.pipeline.media import MediaError, probe_upload
from app.pipeline.tasks import enqueue_lecture

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/uploads", tags=["uploads"])

MAX_UPLOAD_BYTES = 2 * 1024**3
UPLOAD_ID = re.compile(r"[0-9a-f]{64}")
DEFAULT_TITLE = "Загруженная лекция"


class HookModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_pascal, populate_by_name=True)


class HookUpload(HookModel):
    id: str = Field(default="", alias="ID")
    size: int = 0
    size_is_deferred: bool = False
    meta_data: dict[str, str] = Field(default_factory=dict)


class HookRequest(HookModel):
    header: dict[str, list[str]] = Field(default_factory=dict)


class HookEvent(HookModel):
    upload: HookUpload = Field(default_factory=HookUpload)
    http_request: HookRequest = Field(default_factory=HookRequest, alias="HTTPRequest")


class Hook(HookModel):
    type: str
    event: HookEvent = Field(default_factory=HookEvent)


@router.post("/hooks", include_in_schema=False)
async def tusd_hook(hook: Hook, session: SessionDep) -> dict[str, Any]:
    if hook.type == "pre-create":
        try:
            return await pre_create(session, hook)
        except HTTPException as error:
            return reject(error)
    if hook.type == "post-finish":
        await post_finish(session, hook)
    return {}


def reject(error: HTTPException) -> dict[str, Any]:
    return {
        "RejectUpload": True,
        "HTTPResponse": {
            "StatusCode": error.status_code,
            "Body": json.dumps({"detail": error.detail}, ensure_ascii=False),
            "Header": {"Content-Type": "application/json"},
        },
    }


async def hook_user(session: AsyncSession, hook: Hook) -> User:
    header = hook.event.http_request.header
    values = next((v for name, v in header.items() if name.lower() == "authorization"), [])
    value = values[0] if values else ""
    scheme, _, token = value.partition(" ")
    user_id = decode_access_token(token) if scheme.lower() == "bearer" else None
    user = await session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужно войти")
    return user


def course_id_from(upload: HookUpload) -> uuid.UUID | None:
    raw = upload.meta_data.get("course_id")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Неверный курс") from error


def title_from(upload: HookUpload) -> str:
    filename = upload.meta_data.get("filename", "").replace("\\", "/")
    return PurePosixPath(filename).stem.strip()[:300] or DEFAULT_TITLE


async def pre_create(session: AsyncSession, hook: Hook) -> dict[str, Any]:
    user = await hook_user(session, hook)
    upload = hook.event.upload
    if upload.size_is_deferred or upload.size <= 0:
        raise HTTPException(status.HTTP_411_LENGTH_REQUIRED, "Нужно указать размер файла")
    if upload.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Файл больше 2 ГБ")
    course_id = course_id_from(upload)
    if course_id is not None:
        await get_own_course(session, course_id, user)
    return {"ChangeFileInfo": {"ID": user.id.hex + secrets.token_hex(16)}}


async def post_finish(session: AsyncSession, hook: Hook) -> None:
    upload = hook.event.upload
    try:
        user = await hook_user(session, hook)
    except HTTPException:
        logger.warning("Завершение загрузки %s без авторизации", upload.id)
        return
    if not UPLOAD_ID.fullmatch(upload.id) or not upload.id.startswith(user.id.hex):
        logger.warning("Загрузка %s не принадлежит пользователю %s", upload.id, user.id)
        return
    storage_dir = get_settings().storage_dir
    path = storage_dir / "uploads" / upload.id
    info_path = path.with_suffix(".info")
    if not await asyncio.to_thread(upload_complete, path, info_path):
        logger.warning("Загрузка %s не найдена или не завершена", upload.id)
        return
    await session.commit()
    try:
        duration = await probe_upload(path)
    except MediaError as error:
        logger.info("Загрузка %s отклонена: %s", upload.id, error)
        await asyncio.to_thread(discard, path, info_path)
        return

    course_id = None
    try:
        if (requested := course_id_from(upload)) is not None:
            course_id = (await get_own_course(session, requested, user)).id
    except HTTPException:
        logger.info("Курс для загрузки %s не найден, лекция добавлена без курса", upload.id)

    lecture = Lecture(
        owner_id=user.id,
        title=title_from(upload),
        source_type=SourceType.upload,
        duration_sec=duration,
        status=LectureStatus.queued,
    )
    session.add(lecture)
    await session.flush()
    if course_id is not None:
        await add_to_course(session, course_id, lecture.id)
    original = storage_dir / "originals" / str(lecture.id)
    try:
        await asyncio.to_thread(move_original, path, original)
    except FileNotFoundError:
        await session.rollback()
        logger.warning("Загрузка %s уже обработана", upload.id)
        return
    lecture.audio_path = str(original)
    await session.commit()
    await asyncio.to_thread(info_path.unlink, missing_ok=True)

    try:
        await enqueue_lecture(lecture.id)
    except (OSError, RedisError) as error:
        lecture.status = LectureStatus.failed
        await session.commit()
        logger.error("Не удалось поставить лекцию %s в очередь: %s", lecture.id, error)


def upload_complete(path: Path, info_path: Path) -> bool:
    try:
        size = json.loads(info_path.read_text())["Size"]
        return path.stat().st_size == size
    except (OSError, ValueError, KeyError, TypeError):
        return False


def move_original(path: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    path.rename(target)


def discard(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
