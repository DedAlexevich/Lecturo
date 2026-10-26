import uuid

from app.schemas.common import Schema


class SearchHit(Schema):
    lecture_id: uuid.UUID
    lecture_title: str
    start: float
    end: float
    text: str
    score: float
