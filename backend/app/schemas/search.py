import uuid

from app.models import ChunkKind
from app.schemas.common import Schema


class SearchHit(Schema):
    lecture_id: uuid.UUID
    lecture_title: str
    kind: ChunkKind
    start: float | None
    end: float | None
    section: int | None
    text: str
    score: float
