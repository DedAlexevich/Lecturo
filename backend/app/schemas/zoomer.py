import uuid
from datetime import datetime

from pydantic import Field

from app.models import ZoomerVideoStatus
from app.schemas.common import Schema


class ZoomerVideoOut(Schema):
    id: uuid.UUID
    title: str
    source: str
    status: ZoomerVideoStatus
    error: str | None
    enabled: bool
    position: int
    duration_sec: float | None
    width: int | None
    height: int | None
    size_bytes: int | None
    vertical: bool | None
    poster_url: str | None
    video_url: str | None
    created_at: datetime


class ZoomerVideoPatch(Schema):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    source: str | None = Field(default=None, min_length=3, max_length=500)
    enabled: bool | None = None


class ZoomerOrderIn(Schema):
    ids: list[uuid.UUID]


class ZoomerClipOut(Schema):
    id: uuid.UUID
    title: str
    url: str
    poster_url: str
    duration_sec: float | None
