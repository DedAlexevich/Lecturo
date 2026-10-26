import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import Schema


class CourseIn(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""


class CourseOut(Schema):
    id: uuid.UUID
    title: str
    description: str
    lecture_count: int = 0
    created_at: datetime


class CourseLectureIn(Schema):
    lecture_id: uuid.UUID
