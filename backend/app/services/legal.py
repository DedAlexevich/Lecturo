import re
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from app.schemas.legal import LegalDocOut

DOCS_DIR = Path(__file__).resolve().parent.parent / "legal" / "docs"
SLUGS = (
    "terms",
    "privacy",
    "personal-data-consent",
    "offer",
    "refund",
    "cookies",
    "ai-transfer",
    "licenses",
)
TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
REVISION_RE = re.compile(r"^Редакция от (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
EFFECTIVE_RE = re.compile(r"^Вступает в силу с (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
CHANGES_RE = re.compile(r"^Изменения: (.+)$", re.MULTILINE)
NOTICE_DAYS_AFTER = 7
MOSCOW = ZoneInfo("Europe/Moscow")


def today() -> date:
    return datetime.now(MOSCOW).date()


@cache
def load_document(slug: str) -> LegalDocOut:
    content = (DOCS_DIR / f"{slug}.md").read_text(encoding="utf-8")
    title = TITLE_RE.search(content)
    revision = date.fromisoformat(REVISION_RE.search(content).group(1))
    effective = EFFECTIVE_RE.search(content)
    changes = CHANGES_RE.search(content)
    return LegalDocOut(
        slug=slug,
        title=title.group(1),
        content_md=content,
        revision_date=revision,
        effective_date=date.fromisoformat(effective.group(1)) if effective else revision,
        changes=changes.group(1).strip() if changes else None,
    )


def read_document(slug: str) -> LegalDocOut:
    if slug not in SLUGS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    return load_document(slug)


def announced_documents() -> list[LegalDocOut]:
    return [doc for doc in map(load_document, SLUGS) if doc.changes is not None]


def current_updates(today: date) -> list[LegalDocOut]:
    return [
        doc
        for doc in announced_documents()
        if today <= doc.effective_date + timedelta(days=NOTICE_DAYS_AFTER)
    ]
