import uuid

from fastapi import APIRouter, status

from app.core.deps import CurrentUser
from app.core.errors import not_ready
from app.schemas.course import CourseIn, CourseLectureIn, CourseOut, CourseUpdate
from app.schemas.lecture import LectureOut

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("")
async def list_courses(user: CurrentUser) -> list[CourseOut]:
    not_ready()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_course(body: CourseIn, user: CurrentUser) -> CourseOut:
    not_ready()


@router.get("/{course_id}")
async def get_course(course_id: uuid.UUID, user: CurrentUser) -> CourseOut:
    not_ready()


@router.patch("/{course_id}")
async def update_course(course_id: uuid.UUID, body: CourseUpdate, user: CurrentUser) -> CourseOut:
    not_ready()


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(course_id: uuid.UUID, user: CurrentUser) -> None:
    not_ready()


@router.get("/{course_id}/lectures")
async def list_course_lectures(course_id: uuid.UUID, user: CurrentUser) -> list[LectureOut]:
    not_ready()


@router.post("/{course_id}/lectures", status_code=status.HTTP_204_NO_CONTENT)
async def add_course_lecture(
    course_id: uuid.UUID, body: CourseLectureIn, user: CurrentUser
) -> None:
    not_ready()


@router.delete("/{course_id}/lectures/{lecture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_course_lecture(
    course_id: uuid.UUID, lecture_id: uuid.UUID, user: CurrentUser
) -> None:
    not_ready()
