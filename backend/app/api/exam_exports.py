import asyncio
import uuid
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.courses import get_own_course
from app.api.exports import PRIVATE_HEADERS
from app.core.config import get_settings
from app.core.deps import RequireSubscription, SessionDep, bearer, get_current_user
from app.core.security import ALGORITHM, EXPORT_TOKEN_TTL
from app.models import Course, ExamSheet, User
from app.schemas.lecture import ExportLinkOut
from app.services.pdf import exam_sheet_html, render_pdf
from app.services.quota import has_subscription
from app.services.subtitles import content_disposition

router = APIRouter(prefix="/courses/{course_id}/exam-sheet", tags=["exports"])

EXAM_SHEET_EXPORT_SCOPE = "exam-sheet-export"


def create_exam_sheet_token(user_id: uuid.UUID, course_id: uuid.UUID) -> tuple[str, datetime]:
    expires = datetime.now(UTC) + EXPORT_TOKEN_TTL
    payload = {
        "sub": str(user_id),
        "aud": EXAM_SHEET_EXPORT_SCOPE,
        "scope": EXAM_SHEET_EXPORT_SCOPE,
        "course_id": str(course_id),
        "exp": expires,
    }
    return jwt.encode(payload, get_settings().secret_key, algorithm=ALGORITHM), expires


def decode_exam_sheet_token(token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    try:
        payload = jwt.decode(
            token,
            get_settings().secret_key,
            algorithms=[ALGORITHM],
            audience=EXAM_SHEET_EXPORT_SCOPE,
            options={"require": ["exp", "aud", "sub"]},
        )
        if payload.get("scope") != EXAM_SHEET_EXPORT_SCOPE:
            return None
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["course_id"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None


async def exam_sheet_export_user(
    course_id: uuid.UUID,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    token: Annotated[str | None, Query()] = None,
) -> User:
    if token is None:
        user = await get_current_user(session, credentials)
    else:
        grant = decode_exam_sheet_token(token)
        if grant is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Ссылка на скачивание устарела")
        user_id, granted_course_id = grant
        if granted_course_id != course_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Ссылка выдана для другого файла")
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Ссылка на скачивание устарела")
    if not await has_subscription(session, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "subscription_required", "message": "Доступно только с подпиской"},
        )
    return user


async def exportable_exam_sheet(
    session: AsyncSession, user: User, course_id: uuid.UUID
) -> tuple[Course, ExamSheet]:
    course = await get_own_course(session, course_id, user)
    sheet = await session.scalar(select(ExamSheet).where(ExamSheet.course_id == course_id))
    if sheet is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "exam_sheet_not_found", "message": "Памятки по курсу пока нет"},
        )
    return course, sheet


@router.post("/exports/pdf/link", response_model=ExportLinkOut)
async def exam_sheet_export_link(
    course_id: uuid.UUID, request: Request, user: RequireSubscription, session: SessionDep
) -> ExportLinkOut:
    await exportable_exam_sheet(session, user, course_id)
    token, expires_at = create_exam_sheet_token(user.id, course_id)
    path = request.app.url_path_for("export_exam_sheet_pdf", course_id=str(course_id))
    return ExportLinkOut(url=f"{path}?{urlencode({'token': token})}", expires_at=expires_at)


@router.get("/export.pdf", response_class=Response)
async def export_exam_sheet_pdf(
    course_id: uuid.UUID,
    user: Annotated[User, Depends(exam_sheet_export_user)],
    session: SessionDep,
) -> Response:
    course, sheet = await exportable_exam_sheet(session, user, course_id)
    html = exam_sheet_html(course, sheet.content, get_settings().public_url.rstrip("/"))
    content = await asyncio.to_thread(render_pdf, html)
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(f"Памятка. {course.title}", "pdf"),
            **PRIVATE_HEADERS,
        },
    )
