import uuid
from collections.abc import Awaitable, Callable, Iterable
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep, bearer, get_current_user
from app.core.security import ExportFormat, create_export_token, decode_export_token
from app.models import Lecture, User
from app.schemas.lecture import ExportLinkOut
from app.services.pdf import lecture_html, render_pdf_limited
from app.services.rate_limit import enforce_rate_limit
from app.services.subtitles import Segment, build_cues, content_disposition, to_srt, to_vtt

router = APIRouter(prefix="/lectures/{lecture_id}", tags=["exports"])

PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}

PDF_RATE_MESSAGE = "Слишком много выгрузок PDF, попробуйте через минуту"

ENDPOINTS: dict[ExportFormat, str] = {"pdf": "export_pdf", "srt": "export_srt", "vtt": "export_vtt"}


def export_user(export_format: ExportFormat) -> Callable[..., Awaitable[User]]:
    async def dependency(
        lecture_id: uuid.UUID,
        session: SessionDep,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
        token: Annotated[str | None, Query()] = None,
    ) -> User:
        if token is None:
            return await get_current_user(session, credentials)
        grant = decode_export_token(token)
        if grant is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Ссылка на скачивание устарела")
        if grant.lecture_id != lecture_id or grant.export_format != export_format:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Ссылка выдана для другого файла")
        user = await session.get(User, grant.user_id)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Ссылка на скачивание устарела")
        return user

    return dependency


async def exportable_lecture(
    session: AsyncSession, user: User, lecture_id: uuid.UUID, export_format: ExportFormat
) -> Lecture:
    options = (
        (selectinload(Lecture.chapters), selectinload(Lecture.summary))
        if export_format == "pdf"
        else (selectinload(Lecture.segments),)
    )
    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
        .options(*options)
    )
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
    if export_format == "pdf":
        has_summary = lecture.summary is not None and lecture.summary.content_md.strip()
        if not has_summary and not lecture.chapters:
            raise HTTPException(status.HTTP_409_CONFLICT, "Конспект ещё не готов")
    elif not build_cues(lecture.segments):
        raise HTTPException(status.HTTP_409_CONFLICT, "Расшифровки ещё нет")
    return lecture


def subtitles_response(
    lecture: Lecture, render: Callable[[Iterable[Segment]], str], extension: str, media_type: str
) -> Response:
    return Response(
        render(lecture.segments),
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition(lecture.title, extension),
            **PRIVATE_HEADERS,
        },
    )


@router.post("/exports/{export_format}/link", response_model=ExportLinkOut)
async def export_link(
    lecture_id: uuid.UUID,
    export_format: ExportFormat,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
) -> ExportLinkOut:
    await exportable_lecture(session, user, lecture_id, export_format)
    token, expires_at = create_export_token(user.id, lecture_id, export_format)
    path = request.app.url_path_for(ENDPOINTS[export_format], lecture_id=str(lecture_id))
    return ExportLinkOut(url=f"{path}?{urlencode({'token': token})}", expires_at=expires_at)


@router.get("/export.srt", response_class=Response)
async def export_srt(
    lecture_id: uuid.UUID,
    user: Annotated[User, Depends(export_user("srt"))],
    session: SessionDep,
) -> Response:
    lecture = await exportable_lecture(session, user, lecture_id, "srt")
    return subtitles_response(lecture, to_srt, "srt", "application/x-subrip; charset=utf-8")


@router.get("/export.vtt", response_class=Response)
async def export_vtt(
    lecture_id: uuid.UUID,
    user: Annotated[User, Depends(export_user("vtt"))],
    session: SessionDep,
) -> Response:
    lecture = await exportable_lecture(session, user, lecture_id, "vtt")
    return subtitles_response(lecture, to_vtt, "vtt", "text/vtt")


@router.get(
    "/export.pdf",
    response_class=Response,
    responses={status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Слишком много выгрузок PDF"}},
)
async def export_pdf(
    lecture_id: uuid.UUID,
    user: Annotated[User, Depends(export_user("pdf"))],
    session: SessionDep,
) -> Response:
    settings = get_settings()
    await enforce_rate_limit(
        settings.redis_url,
        f"rate:export-pdf:{user.id}",
        settings.pdf_export_rate_limit,
        settings.pdf_export_rate_window_seconds,
        PDF_RATE_MESSAGE,
    )
    lecture = await exportable_lecture(session, user, lecture_id, "pdf")
    html = lecture_html(lecture, settings.public_url.rstrip("/"))
    content = await render_pdf_limited(html)
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(lecture.title, "pdf"),
            **PRIVATE_HEADERS,
        },
    )
