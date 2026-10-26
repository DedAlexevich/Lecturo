import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, SessionDep
from app.models import Course, Lecture, User, course_lectures
from app.schemas.course import CourseIn, CourseLectureIn, CourseOut, CourseUpdate
from app.schemas.lecture import LectureOut

router = APIRouter(prefix="/courses", tags=["courses"])

lecture_count = (
    select(func.count())
    .where(course_lectures.c.course_id == Course.id)
    .correlate(Course)
    .scalar_subquery()
)


async def get_own_course(session: AsyncSession, course_id: uuid.UUID, user: User) -> Course:
    course = await session.scalar(
        select(Course).where(Course.id == course_id, Course.owner_id == user.id)
    )
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Курс не найден")
    return course


async def course_out(session: AsyncSession, course: Course) -> CourseOut:
    count = await session.scalar(select(lecture_count).where(Course.id == course.id))
    return CourseOut.model_validate(course).model_copy(update={"lecture_count": count})


@router.get("")
async def list_courses(user: CurrentUser, session: SessionDep) -> list[CourseOut]:
    rows = await session.execute(
        select(Course, lecture_count)
        .where(Course.owner_id == user.id)
        .order_by(Course.created_at.desc())
    )
    return [
        CourseOut.model_validate(course).model_copy(update={"lecture_count": count})
        for course, count in rows
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_course(body: CourseIn, user: CurrentUser, session: SessionDep) -> CourseOut:
    course = Course(owner_id=user.id, title=body.title, description=body.description)
    session.add(course)
    await session.commit()
    await session.refresh(course)
    return CourseOut.model_validate(course)


@router.get("/{course_id}")
async def get_course(course_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> CourseOut:
    course = await get_own_course(session, course_id, user)
    return await course_out(session, course)


@router.patch("/{course_id}")
async def update_course(
    course_id: uuid.UUID, body: CourseUpdate, user: CurrentUser, session: SessionDep
) -> CourseOut:
    course = await get_own_course(session, course_id, user)
    for field, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(course, field, value)
    await session.commit()
    await session.refresh(course)
    return await course_out(session, course)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(course_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    course = await get_own_course(session, course_id, user)
    await session.delete(course)
    await session.commit()


@router.get("/{course_id}/lectures")
async def list_course_lectures(
    course_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[LectureOut]:
    await get_own_course(session, course_id, user)
    rows = await session.scalars(
        select(Lecture)
        .join(course_lectures, course_lectures.c.lecture_id == Lecture.id)
        .where(course_lectures.c.course_id == course_id)
        .order_by(course_lectures.c.position, course_lectures.c.added_at)
    )
    return [LectureOut.model_validate(row) for row in rows]


@router.post("/{course_id}/lectures", status_code=status.HTTP_204_NO_CONTENT)
async def add_course_lecture(
    course_id: uuid.UUID, body: CourseLectureIn, user: CurrentUser, session: SessionDep
) -> None:
    await get_own_course(session, course_id, user)
    lecture = await session.scalar(
        select(Lecture.id).where(Lecture.id == body.lecture_id, Lecture.owner_id == user.id)
    )
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекция не найдена")
    next_position = (
        select(func.coalesce(func.max(course_lectures.c.position) + 1, 0))
        .where(course_lectures.c.course_id == course_id)
        .scalar_subquery()
    )
    await session.execute(
        insert(course_lectures)
        .values(course_id=course_id, lecture_id=body.lecture_id, position=next_position)
        .on_conflict_do_nothing()
    )
    await session.commit()


@router.delete("/{course_id}/lectures/{lecture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_course_lecture(
    course_id: uuid.UUID, lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> None:
    await get_own_course(session, course_id, user)
    result = await session.execute(
        delete(course_lectures).where(
            course_lectures.c.course_id == course_id, course_lectures.c.lecture_id == lecture_id
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Лекции нет в курсе")
    await session.commit()
