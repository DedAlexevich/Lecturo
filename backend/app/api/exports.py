import asyncio
import uuid
from collections.abc import Callable, Iterable

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep
from app.models import Lecture, User
from app.services.pdf import lecture_html, render_pdf
from app.services.subtitles import Segment, build_cues, content_disposition, to_srt, to_vtt

router = APIRouter(prefix="/lectures/{lecture_id}", tags=["exports"])


async def subtitles_response(
    session: AsyncSession,
    user: User,
    lecture_id: uuid.UUID,
    render: Callable[[Iterable[Segment]], str],
    extension: str,
    media_type: str,
) -> Response:
    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
        .options(selectinload(Lecture.segments))
    )
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
    if not build_cues(lecture.segments):
        raise HTTPException(status.HTTP_409_CONFLICT, "Расшифровки ещё нет")
    return Response(
        render(lecture.segments),
        media_type=media_type,
        headers={"Content-Disposition": content_disposition(lecture.title, extension)},
    )


@router.get("/export.srt", response_class=Response)
async def export_srt(lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    return await subtitles_response(
        session, user, lecture_id, to_srt, "srt", "application/x-subrip; charset=utf-8"
    )


@router.get("/export.vtt", response_class=Response)
async def export_vtt(lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    return await subtitles_response(session, user, lecture_id, to_vtt, "vtt", "text/vtt")


@router.get("/export.pdf", response_class=Response)
async def export_pdf(lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
        .options(selectinload(Lecture.chapters), selectinload(Lecture.summary))
    )
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
    has_summary = lecture.summary is not None and lecture.summary.content_md.strip()
    if not has_summary and not lecture.chapters:
        raise HTTPException(status.HTTP_409_CONFLICT, "Конспект ещё не готов")

    html = lecture_html(lecture, get_settings().public_url.rstrip("/"))
    content = await asyncio.to_thread(render_pdf, html)
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(lecture.title, "pdf")},
    )
