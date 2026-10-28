import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import AuthIdentity, AuthProvider, BusinessEventKind, Lecture, Payment, User
from app.pipeline.jobs import cancel_lecture_jobs
from app.pipeline.stages import discard_operation_objects, lock_operation_objects
from app.schemas.user import AccountDeleteIn
from app.services import business_events
from app.services.admin import user_label
from app.services.admin_logs import mask_text
from app.services.auth import hash_password, verify_password
from app.services.auth_tokens import bump_token_version, revoke_unused_tokens
from app.services.quota import keep_weekly_usage
from app.services.telegram_auth import verify_login_widget, verify_webapp_init_data

logger = logging.getLogger(__name__)

CONFIRMATION_REQUIRED = "Подтвердите удаление паролем или данными Telegram"
CONFIRMATION_FAILED = "Подтверждение не прошло"
WRONG_PASSWORD = "Неверный текущий пароль"


async def has_telegram_identity(session: AsyncSession, user: User, telegram_id: int) -> bool:
    identity = await session.scalar(
        select(AuthIdentity.id).where(
            AuthIdentity.user_id == user.id,
            AuthIdentity.provider == AuthProvider.telegram,
            AuthIdentity.provider_user_id == str(telegram_id),
        )
    )
    return identity is not None


async def confirm_deletion(session: AsyncSession, user: User, body: AccountDeleteIn) -> None:
    if body.password is not None:
        if not user.password_hash or not verify_password(user.password_hash, body.password):
            raise HTTPException(status.HTTP_403_FORBIDDEN, CONFIRMATION_FAILED)
        return
    if body.telegram is not None:
        verify_login_widget(body.telegram)
        telegram_id = body.telegram.id
    elif body.telegram_init_data is not None:
        telegram_id = verify_webapp_init_data(body.telegram_init_data)["id"]
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, CONFIRMATION_REQUIRED)
    if not await has_telegram_identity(session, user, telegram_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, CONFIRMATION_FAILED)


async def update_display_name(session: AsyncSession, user: User, display_name: str) -> None:
    user.display_name = display_name
    await session.commit()


async def change_password(
    session: AsyncSession, user: User, current_password: str | None, new_password: str
) -> int:
    if user.password_hash:
        if current_password is None or not verify_password(user.password_hash, current_password):
            raise HTTPException(status.HTTP_403_FORBIDDEN, WRONG_PASSWORD)
    user.password_hash = hash_password(new_password)
    await revoke_unused_tokens(session, user.id)
    version = await bump_token_version(session, user.id)
    await session.commit()
    return version


def lecture_files(lecture_id: uuid.UUID, paths: list[str | None]) -> set[Path]:
    storage_dir = get_settings().storage_dir
    files = {
        storage_dir / "originals" / str(lecture_id),
        storage_dir / "audio" / f"{lecture_id}.opus",
        storage_dir / "videos" / f"{lecture_id}.mp4",
    }
    files.update(Path(path) for path in paths if path)
    for folder in ("audio", "tmp"):
        directory = storage_dir / folder
        if directory.is_dir():
            files.update(directory.glob(f"{lecture_id}.*"))
    return files


def remove_files(files: set[Path], user_id: uuid.UUID | None = None) -> None:
    uploads_dir = get_settings().storage_dir / "uploads"
    if user_id is not None and uploads_dir.is_dir():
        files.update(uploads_dir.glob(f"{user_id.hex}*"))
    for file in files:
        try:
            file.unlink(missing_ok=True)
        except OSError:
            logger.exception("Не удалось удалить файл %s", file)


async def delete_account(session: AsyncSession, user: User) -> None:
    rows = await session.execute(
        select(Lecture.id, Lecture.video_path, Lecture.audio_path).where(
            Lecture.owner_id == user.id
        )
    )
    files: set[Path] = set()
    lecture_ids = []
    for lecture_id, video_path, audio_path in rows.all():
        files |= lecture_files(lecture_id, [video_path, audio_path])
        lecture_ids.append(lecture_id)
    stt_objects = await lock_operation_objects(session, lecture_ids)
    user_id = user.id
    label = mask_text(user_label(user))
    await keep_weekly_usage(session, user)
    await session.execute(update(Payment).where(Payment.user_id == user_id).values(raw={}))
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()
    await cancel_lecture_jobs(lecture_ids)
    await business_events.record_event(
        BusinessEventKind.account_deleted, user_id=user_id, label=label
    )
    await asyncio.to_thread(remove_files, files, user_id)
    await discard_operation_objects(stt_objects)
