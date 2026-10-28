import uuid
from datetime import datetime

from pydantic import Field

from app.models import AdminAction
from app.schemas.common import Schema


class AdminOut(Schema):
    id: uuid.UUID
    email: str | None
    display_name: str
    created_at: datetime


class AdminGrantIn(Schema):
    identifier: str = Field(min_length=1, max_length=320)


class AuditEntryOut(Schema):
    id: uuid.UUID
    created_at: datetime
    actor_id: uuid.UUID | None
    actor_label: str
    action: AdminAction
    target_type: str
    target_id: str | None
    target_label: str
    details: dict


class AuditPage(Schema):
    total: int
    items: list[AuditEntryOut]
