import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints

from app.schemas.common import Schema

CourseTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class CourseIn(Schema):
    title: CourseTitle
    description: str = Field(default="", max_length=2000)


class CourseOut(Schema):
    id: uuid.UUID
    title: str
    description: str
    lecture_count: int = 0
    created_at: datetime


class CourseLectureIn(Schema):
    lecture_id: uuid.UUID


class CourseUpdate(Schema):
    title: CourseTitle | None = None
    description: str | None = Field(default=None, max_length=2000)
