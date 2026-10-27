import logging
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep
from app.models import Complaint, Course, Lecture, LectureStatus, ShareLink, User, course_lectures
from app.pipeline.video_access import signed_video_url
from app.schemas.share import (
    ComplaintIn,
    PublicCourseOut,
    PublicLectureOut,
    PublicLectureSummary,
    PublicShareOut,
    ShareIn,
    ShareOut,
)
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


async def public_lecture(
    session: AsyncSession, lecture_id: uuid.UUID, token: str
) -> PublicLectureOut:
    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id)
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
        video_url=signed_video_url(lecture.id, token) if lecture.video_path else None,
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
    rows = await session.execute(
        select(Lecture, ShareLink.token)
        .join(course_lectures, course_lectures.c.lecture_id == Lecture.id)
        .outerjoin(
            ShareLink,
            (ShareLink.lecture_id == Lecture.id)
            & (ShareLink.owner_id == course.owner_id)
            & ShareLink.revoked_at.is_(None),
        )
        .where(
            course_lectures.c.course_id == course_id,
            Lecture.status == LectureStatus.ready,
        )
        .order_by(course_lectures.c.position, course_lectures.c.added_at)
    )
    lectures: dict[uuid.UUID, PublicLectureSummary] = {}
    for lecture, token in rows:
        if lecture.id not in lectures:
            lectures[lecture.id] = PublicLectureSummary(
                id=lecture.id,
                title=lecture.title,
                duration_sec=lecture.duration_sec,
                processed_locally=lecture.processed_locally,
                share_token=token,
            )
    return PublicCourseOut(
        id=course.id,
        title=course.title,
        description=course.description,
        lectures=list(lectures.values()),
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


@router.post("/public/{token}/complaints", status_code=status.HTTP_204_NO_CONTENT)
async def complain(token: str, body: ComplaintIn, request: Request, session: SessionDep) -> None:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        settings.redis_url,
        f"rate:complaints:ip:{ip}",
        settings.complaints_rate_limit,
        settings.complaints_rate_window_seconds,
    )
    share = await get_active_share(session, token)
    if share.lecture_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Выберите лекцию для жалобы")
    lecture_id = await session.scalar(
        select(Lecture.id).where(
            Lecture.id == share.lecture_id, Lecture.status == LectureStatus.ready
        )
    )
    if lecture_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, SHARE_NOT_FOUND)
    reason = body.reason.strip()
    if not reason or len(reason) > 5000:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Укажите причину жалобы до 5000 символов"
        )
    complaint = Complaint(lecture_id=lecture_id, reason=reason)
    session.add(complaint)
    await session.commit()
    logger.warning(
        "Новая жалоба: complaint_id=%s lecture_id=%s owner_id=%s",
        complaint.id,
        lecture_id,
        share.owner_id,
    )
