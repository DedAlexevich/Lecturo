import uuid
from datetime import datetime

from app.schemas.common import Schema
from app.schemas.lecture import ChapterOut, SegmentOut, SummaryOut


class ShareIn(Schema):
    lecture_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None


class ShareOut(Schema):
    token: str
    url: str
    lecture_id: uuid.UUID | None
    course_id: uuid.UUID | None
    revoked_at: datetime | None
    created_at: datetime


class ComplaintIn(Schema):
    reason: str
    lecture_id: uuid.UUID | None = None


class PublicLectureOut(Schema):
    id: uuid.UUID
    title: str
    embed_url: str | None
    video_url: str | None
    duration_sec: float | None
    processed_locally: bool
    segments: list[SegmentOut]
    chapters: list[ChapterOut]
    summary: SummaryOut | None


class PublicLectureSummary(Schema):
    id: uuid.UUID
    title: str
    duration_sec: float | None
    processed_locally: bool


class PublicCourseOut(Schema):
    id: uuid.UUID
    title: str
    description: str
    lectures: list[PublicLectureSummary]


class PublicShareOut(Schema):
    lecture: PublicLectureOut | None = None
    course: PublicCourseOut | None = None


class CopyIn(Schema):
    lecture_id: uuid.UUID | None = None


class CopyOut(Schema):
    lecture_id: uuid.UUID | None
    course_id: uuid.UUID | None
    lecture_ids: list[uuid.UUID]
    created: bool


class CopyConflictDetail(Schema):
    message: str
    lecture_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None


class CopyConflictOut(Schema):
    detail: CopyConflictDetail
