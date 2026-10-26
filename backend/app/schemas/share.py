import uuid
from datetime import datetime

from app.schemas.common import Schema


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
