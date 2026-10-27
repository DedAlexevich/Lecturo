import uuid
from datetime import datetime

from pydantic import Field, HttpUrl, field_validator

from app.models import LectureStatus, SourceType, StepName, StepStatus
from app.pipeline.download import with_scheme
from app.schemas.common import Schema


class LinkIn(Schema):
    url: HttpUrl
    title: str | None = Field(default=None, max_length=300)
    course_id: uuid.UUID | None = None

    @field_validator("url", mode="before")
    @classmethod
    def add_scheme(cls, value: object) -> object:
        return with_scheme(value) if isinstance(value, str) else value


class SegmentOut(Schema):
    start: float
    end: float
    text: str


class ChapterOut(Schema):
    start: float
    end: float
    title: str
    summary: str


class SummaryOut(Schema):
    content_md: str


class StepOut(Schema):
    step: StepName
    status: StepStatus
    progress: float
    error: str | None


class LectureOut(Schema):
    id: uuid.UUID
    title: str
    source_type: SourceType
    source_url: str | None
    embed_url: str | None
    duration_sec: float | None
    status: LectureStatus
    processed_locally: bool
    video_expires_at: datetime | None
    created_at: datetime


class LinkLectureOut(LectureOut):
    existing: bool = False


class LectureDetail(LectureOut):
    video_url: str | None = None
    audio_only: bool = False
    audio_url: str | None = None
    steps: list[StepOut]
    segments: list[SegmentOut]
    chapters: list[ChapterOut]
    summary: SummaryOut | None


class QuizQuestion(Schema):
    question: str
    options: list[str]
    correct_index: int
    explanation: str
    timestamp: float


class QuizOut(Schema):
    lecture_id: uuid.UUID
    questions: list[QuizQuestion]


class ExamSheetOut(Schema):
    course_id: uuid.UUID
    tickets: list[str]
    definitions: list[dict[str, str]]
    cheatsheet_md: str


class LocalResultIn(Schema):
    title: str = Field(max_length=300)
    duration_sec: float = Field(gt=0, le=4 * 3600)
    language: str = "ru"
    model: str
    segments: list[SegmentOut]
    chapters: list[ChapterOut] = []
    summary_md: str | None = None


class LectureUpdate(Schema):
    title: str = Field(min_length=1, max_length=300)


class LectureStatusOut(Schema):
    id: uuid.UUID
    status: LectureStatus
    queue_position: int | None
    steps: list[StepOut]
