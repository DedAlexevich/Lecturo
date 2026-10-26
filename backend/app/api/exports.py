import uuid

from fastapi import APIRouter, Response

from app.core.deps import CurrentUser
from app.core.errors import not_ready

router = APIRouter(prefix="/lectures/{lecture_id}", tags=["exports"])


@router.get("/export.srt", response_class=Response)
async def export_srt(lecture_id: uuid.UUID, user: CurrentUser) -> Response:
    not_ready()


@router.get("/export.vtt", response_class=Response)
async def export_vtt(lecture_id: uuid.UUID, user: CurrentUser) -> Response:
    not_ready()


@router.get("/export.pdf", response_class=Response)
async def export_pdf(lecture_id: uuid.UUID, user: CurrentUser) -> Response:
    not_ready()
