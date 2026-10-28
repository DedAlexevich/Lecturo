import enum
from datetime import datetime

from pydantic import Field

from app.schemas.common import Schema


class BackupIntegrity(enum.StrEnum):
    ok = "ok"
    broken = "broken"
    encrypted = "encrypted"


class BackupOut(Schema):
    name: str
    size: int
    modified_at: datetime
    source: str
    integrity: BackupIntegrity
    dump_major: int | None
    restorable: bool


class BackupJobOut(Schema):
    id: str
    kind: str
    state: str
    step: str
    message: str
    backup: str | None
    started_at: datetime
    finished_at: datetime | None


class BackupsOut(Schema):
    items: list[BackupOut]
    job: BackupJobOut | None
    maintenance: bool


class RestoreIn(Schema):
    password: str = Field(min_length=1, max_length=256)
    confirmation: str = Field(max_length=32)


class MaintenanceOut(Schema):
    active: bool
    message: str
