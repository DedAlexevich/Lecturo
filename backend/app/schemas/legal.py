from datetime import date

from app.schemas.common import Schema


class LegalDocSummary(Schema):
    slug: str
    title: str


class LegalDocOut(LegalDocSummary):
    content_md: str
    revision_date: date
