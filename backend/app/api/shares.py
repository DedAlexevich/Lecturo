import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep, bearer, user_by_token
from app.models import Complaint, Course, Lecture, LectureStatus, ShareLink, User, course_lectures
from app.pipeline.video_access import playable_video_url
from app.schemas.share import (
    ComplaintIn,
    PublicCourseOut,
    PublicLectureOut,
    PublicLectureSummary,
    PublicShareOut,
    ShareIn,
    ShareOut,
)
from app.services.mail import send_mail
from app.services.rate_limit import enforce_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["shares"])

SHARE_NOT_FOUND = "Ссылка не найдена"


def share_out(share: ShareLink) -> ShareOut:
    base_url = get_settings().public_url.rstrip("/")
    return ShareOut(
        token=share.token,
        url=f"{base_url}/s/{share.token}",
        lecture_id=share.lecture_id,
        course_id=share.course_id,
        revoked_at=share.revoked_at,
        created_at=share.created_at,
    )


def is_confirmed(user: User) -> bool:
    return user.email_verified_at is not None or user.telegram_chat_id is not None


async def get_active_share(session: AsyncSession, token: str) -> ShareLink:
    share = await session.scalar(
        select(ShareLink).where(ShareLink.token == token, ShareLink.revoked_at.is_(None))
    )
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SHARE_NOT_FOUND)
    return share


def shared_with(token: str) -> ColumnElement[bool]:
    return (
        select(ShareLink.id)
        .outerjoin(course_lectures, course_lectures.c.course_id == ShareLink.course_id)
        .where(
            ShareLink.token == token,
            ShareLink.revoked_at.is_(None),
            or_(ShareLink.lecture_id == Lecture.id, course_lectures.c.lecture_id == Lecture.id),
        )
        .exists()
    )


async def public_lecture(
    session: AsyncSession, lecture_id: uuid.UUID, token: str
) -> PublicLectureOut:
    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id, shared_with(token))
        .options(
            selectinload(Lecture.segments),
            selectinload(Lecture.chapters),
            selectinload(Lecture.summary),
        )
    )
    if lecture is None or lecture.status != LectureStatus.ready:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SHARE_NOT_FOUND)
    return PublicLectureOut(
        id=lecture.id,
        title=lecture.title,
        embed_url=lecture.embed_url,
        video_url=playable_video_url(lecture, token),
        duration_sec=lecture.duration_sec,
        processed_locally=lecture.processed_locally,
        segments=lecture.segments,
        chapters=lecture.chapters,
        summary=lecture.summary,
    )


async def public_course(session: AsyncSession, course_id: uuid.UUID) -> PublicCourseOut:
    course = await session.get(Course, course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SHARE_NOT_FOUND)
    lectures = await session.scalars(
        select(Lecture)
        .join(course_lectures, course_lectures.c.lecture_id == Lecture.id)
        .where(
            course_lectures.c.course_id == course_id,
            Lecture.status == LectureStatus.ready,
        )
        .order_by(course_lectures.c.position, course_lectures.c.added_at)
    )
    return PublicCourseOut(
        id=course.id,
        title=course.title,
        description=course.description,
        lectures=[PublicLectureSummary.model_validate(lecture) for lecture in lectures],
    )


@router.post("/shares", status_code=status.HTTP_201_CREATED)
async def create_share(body: ShareIn, user: CurrentUser, session: SessionDep) -> ShareOut:
    if not is_confirmed(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Подтвердите почту или привяжите Telegram, чтобы делиться"
        )
    if (body.lecture_id is None) == (body.course_id is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Укажите либо лекцию, либо курс")
    if body.lecture_id is not None:
        lecture_status = await session.scalar(
            select(Lecture.status).where(Lecture.id == body.lecture_id, Lecture.owner_id == user.id)
        )
        if lecture_status is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
        if lecture_status != LectureStatus.ready:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Поделиться можно только обработанной лекцией"
            )
    else:
        target = await session.scalar(
            select(Course.id).where(Course.id == body.course_id, Course.owner_id == user.id)
        )
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Курс не найден")

    share = ShareLink(
        token=secrets.token_urlsafe(24),
        owner_id=user.id,
        lecture_id=body.lecture_id,
        course_id=body.course_id,
    )
    session.add(share)
    await session.commit()
    await session.refresh(share)
    return share_out(share)


@router.get("/shares")
async def list_shares(user: CurrentUser, session: SessionDep) -> list[ShareOut]:
    rows = await session.scalars(
        select(ShareLink)
        .where(ShareLink.owner_id == user.id, ShareLink.revoked_at.is_(None))
        .order_by(ShareLink.created_at.desc())
    )
    return [share_out(share) for share in rows]


@router.delete("/shares/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(token: str, user: CurrentUser, session: SessionDep) -> None:
    revoked = await session.scalar(
        update(ShareLink)
        .where(
            ShareLink.token == token,
            ShareLink.owner_id == user.id,
            ShareLink.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
        .returning(ShareLink.id)
    )
    if revoked is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SHARE_NOT_FOUND)
    await session.commit()


@router.get("/public/{token}")
async def get_public(token: str, session: SessionDep) -> PublicShareOut:
    share = await get_active_share(session, token)
    if share.lecture_id is not None:
        return PublicShareOut(lecture=await public_lecture(session, share.lecture_id, token))
    return PublicShareOut(course=await public_course(session, share.course_id))


@router.get("/public/{token}/lectures/{lecture_id}")
async def get_public_course_lecture(
    token: str, lecture_id: uuid.UUID, session: SessionDep
) -> PublicLectureOut:
    await get_active_share(session, token)
    return await public_lecture(session, lecture_id, token)


def complaint_mail(complaint: Complaint, owner_id: uuid.UUID) -> str:
    reporter = str(complaint.reporter_id) if complaint.reporter_id else "без входа"
    return (
        f"Жалоба: {complaint.id}\n"
        f"Лекция: {complaint.lecture_id}\n"
        f"Владелец: {owner_id}\n"
        f"Автор жалобы: {reporter}\n\n"
        f"{complaint.reason}"
    )


@router.post("/public/{token}/complaints", status_code=status.HTTP_204_NO_CONTENT)
async def complain(
    token: str,
    body: ComplaintIn,
    request: Request,
    session: SessionDep,
    background: BackgroundTasks,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        settings.redis_url,
        f"rate:complaints:ip:{ip}",
        settings.complaints_rate_limit,
        settings.complaints_rate_window_seconds,
    )
    share = await get_active_share(session, token)
    target_id = share.lecture_id or body.lecture_id
    if target_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Выберите лекцию для жалобы")
    lecture_id = await session.scalar(
        select(Lecture.id).where(
            Lecture.id == target_id, Lecture.status == LectureStatus.ready, shared_with(token)
        )
    )
    if lecture_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SHARE_NOT_FOUND)
    reporter = await user_by_token(session, credentials.credentials) if credentials else None
    complaint = Complaint(
        lecture_id=lecture_id, reporter_id=reporter.id if reporter else None, reason=body.reason
    )
    session.add(complaint)
    await session.commit()
    logger.warning(
        "Новая жалоба: complaint_id=%s lecture_id=%s owner_id=%s",
        complaint.id,
        lecture_id,
        share.owner_id,
    )
    if settings.complaints_email:
        background.add_task(
            send_mail,
            settings.complaints_email,
            "Новая жалоба в Lecturo",
            complaint_mail(complaint, share.owner_id),
        )
