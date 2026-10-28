import uuid
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.exports import PRIVATE_HEADERS, subtitles_response
from app.api.shares import SHARE_NOT_FOUND, get_active_share, shared_with
from app.core.config import get_settings
from app.core.deps import SessionDep
from app.core.security import (
    PublicExportFormat,
    create_public_export_token,
    decode_public_export_token,
)
from app.models import Lecture, LectureStatus
from app.schemas.lecture import ExportLinkOut
from app.services.pdf import lecture_html, render_pdf_limited
from app.services.rate_limit import enforce_rate_limit
from app.services.subtitles import build_cues, content_disposition, to_srt, to_vtt

router = APIRouter(prefix="/public/{token}/lectures/{lecture_id}", tags=["shares"])

ENDPOINTS: dict[PublicExportFormat, str] = {
    "pdf": "public_export_pdf",
    "md": "public_export_md",
    "srt": "public_export_srt",
    "vtt": "public_export_vtt",
}

GrantQuery = Annotated[str, Query()]


async def limit_exports(request: Request) -> None:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        settings.redis_url,
        f"rate:public-export:ip:{ip}",
        settings.public_export_rate_limit,
        settings.public_export_rate_window_seconds,
    )


async def exportable_shared_lecture(
    session: AsyncSession, token: str, lecture_id: uuid.UUID, export_format: PublicExportFormat
) -> Lecture:
    await get_active_share(session, token)
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
    has_summary = lecture.summary is not None and bool(lecture.summary.content_md.strip())
    if export_format == "pdf" and not has_summary and not lecture.chapters:
        raise HTTPException(status.HTTP_409_CONFLICT, "Конспект ещё не готов")
    if export_format == "md" and not has_summary:
        raise HTTPException(status.HTTP_409_CONFLICT, "Конспект ещё не готов")
    if export_format in ("srt", "vtt") and not build_cues(lecture.segments):
        raise HTTPException(status.HTTP_409_CONFLICT, "Расшифровки ещё нет")
    return lecture


async def granted_lecture(
    session: AsyncSession,
    token: str,
    lecture_id: uuid.UUID,
    grant: str,
    export_format: PublicExportFormat,
) -> Lecture:
    decoded = decode_public_export_token(grant)
    if decoded is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Ссылка на скачивание устарела")
    if (
        decoded.share_token != token
        or decoded.lecture_id != lecture_id
        or decoded.export_format != export_format
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ссылка выдана для другого файла")
    return await exportable_shared_lecture(session, token, lecture_id, export_format)


@router.post("/exports/{export_format}/link")
async def public_export_link(
    token: str,
    lecture_id: uuid.UUID,
    export_format: PublicExportFormat,
    request: Request,
    session: SessionDep,
) -> ExportLinkOut:
    await limit_exports(request)
    await exportable_shared_lecture(session, token, lecture_id, export_format)
    grant, expires_at = create_public_export_token(token, lecture_id, export_format)
    path = request.app.url_path_for(
        ENDPOINTS[export_format], token=token, lecture_id=str(lecture_id)
    )
    return ExportLinkOut(url=f"{path}?{urlencode({'grant': grant})}", expires_at=expires_at)


@router.get("/export.srt", response_class=Response)
async def public_export_srt(
    token: str, lecture_id: uuid.UUID, grant: GrantQuery, session: SessionDep
) -> Response:
    lecture = await granted_lecture(session, token, lecture_id, grant, "srt")
    return subtitles_response(lecture, to_srt, "srt", "application/x-subrip; charset=utf-8")


@router.get("/export.vtt", response_class=Response)
async def public_export_vtt(
    token: str, lecture_id: uuid.UUID, grant: GrantQuery, session: SessionDep
) -> Response:
    lecture = await granted_lecture(session, token, lecture_id, grant, "vtt")
    return subtitles_response(lecture, to_vtt, "vtt", "text/vtt")


@router.get("/export.md", response_class=Response)
async def public_export_md(
    token: str, lecture_id: uuid.UUID, grant: GrantQuery, session: SessionDep
) -> Response:
    lecture = await granted_lecture(session, token, lecture_id, grant, "md")
    content = f"# {lecture.title}\n\n{lecture.summary.content_md.strip()}\n"
    return Response(
        content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": content_disposition(lecture.title, "md"),
            **PRIVATE_HEADERS,
        },
    )


@router.get("/export.pdf", response_class=Response)
async def public_export_pdf(
    token: str, lecture_id: uuid.UUID, grant: GrantQuery, session: SessionDep
) -> Response:
    lecture = await granted_lecture(session, token, lecture_id, grant, "pdf")
    share = await get_active_share(session, token)
    base_url = get_settings().public_url.rstrip("/")
    page_url = f"{base_url}/s/{token}" + ("" if share.lecture_id else f"/{lecture_id}")
    html = lecture_html(lecture, base_url, page_url)
    content = await render_pdf_limited(html)
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(lecture.title, "pdf"),
            **PRIVATE_HEADERS,
        },
    )
