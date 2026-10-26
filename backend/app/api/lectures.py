import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, SessionDep
from app.core.errors import not_ready
from app.models import Lecture
from app.schemas.lecture import (
    LectureDetail,
    LectureOut,
    LectureStatusOut,
    LectureUpdate,
    LinkIn,
    QuizOut,
)

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


@router.post("/link", status_code=status.HTTP_201_CREATED)
async def add_link(body: LinkIn, user: CurrentUser) -> LectureOut:
    not_ready()


@router.patch("/{lecture_id}")
async def update_lecture(
    lecture_id: uuid.UUID, body: LectureUpdate, user: CurrentUser
) -> LectureOut:
    not_ready()


@router.delete("/{lecture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lecture(lecture_id: uuid.UUID, user: CurrentUser) -> None:
    not_ready()


@router.get("/{lecture_id}/status")
async def get_status(lecture_id: uuid.UUID, user: CurrentUser) -> LectureStatusOut:
    not_ready()


@router.post("/{lecture_id}/retry")
async def retry(lecture_id: uuid.UUID, user: CurrentUser) -> LectureStatusOut:
    not_ready()


@router.post("/{lecture_id}/quiz", status_code=status.HTTP_202_ACCEPTED)
async def create_quiz(lecture_id: uuid.UUID, user: CurrentUser) -> None:
    not_ready()


@router.get("/{lecture_id}/quiz")
async def get_quiz(lecture_id: uuid.UUID, user: CurrentUser) -> QuizOut:
    not_ready()
