import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, SessionDep
from app.models import Lecture
from app.schemas.lecture import LectureDetail, LectureOut

router = APIRouter(prefix="/lectures", tags=["lectures"])


@router.get("")
async def list_lectures(user: CurrentUser, session: SessionDep) -> list[LectureOut]:
    rows = await session.scalars(
        select(Lecture).where(Lecture.owner_id == user.id).order_by(Lecture.created_at.desc())
    )
    return [LectureOut.model_validate(row) for row in rows]


@router.get("/{lecture_id}")
async def get_lecture(
    lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> LectureDetail:
    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
        .options(
            selectinload(Lecture.steps),
            selectinload(Lecture.segments),
            selectinload(Lecture.chapters),
            selectinload(Lecture.summary),
        )
    )
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
    video_url = f"/media/{lecture.id}.mp4" if lecture.video_path else None
    return LectureDetail.model_validate(lecture).model_copy(update={"video_url": video_url})
