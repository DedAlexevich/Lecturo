import uuid
from datetime import datetime

from app.models import BusinessEventKind, LectureStatus, StepName
from app.schemas.common import Schema
from app.services.admin_logs import LogLevel, LogService


class LogLineOut(Schema):
    level: LogLevel | None
    text: str


class LogTailOut(Schema):
    service: LogService
    lines: list[LogLineOut]
    offset: int
    size: int
    modified_at: datetime


class ProcessingErrorOut(Schema):
    lecture_id: uuid.UUID
    lecture_title: str
    lecture_status: LectureStatus
    step: StepName
    error: str
    attempts: int
    failed_at: datetime
    user_id: uuid.UUID | None
    user_label: str
    can_retry: bool


class ProcessingErrorsPage(Schema):
    total: int
    items: list[ProcessingErrorOut]


class BusinessEventOut(Schema):
    id: uuid.UUID
    created_at: datetime
    kind: BusinessEventKind
    user_id: uuid.UUID | None
    user_label: str
    details: dict


class BusinessEventsPage(Schema):
    total: int
    items: list[BusinessEventOut]
