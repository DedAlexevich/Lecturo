from datetime import date

from app.schemas.common import Schema


class LegalDocSummary(Schema):
    slug: str
    title: str


class LegalUpdateOut(LegalDocSummary):
    revision_date: date
    effective_date: date
    changes: str | None


class LegalDocOut(LegalUpdateOut):
    content_md: str
