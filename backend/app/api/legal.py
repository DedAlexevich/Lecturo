import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.schemas.legal import LegalDocOut, LegalDocSummary

router = APIRouter(prefix="/legal", tags=["legal"])

DOCS_DIR = Path(__file__).resolve().parent.parent / "legal" / "docs"
SLUGS = (
    "terms",
    "privacy",
    "personal-data-consent",
    "offer",
    "refund",
    "cookies",
    "ai-transfer",
)
TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
REVISION_RE = re.compile(r"^Редакция от (\d{4}-\d{2}-\d{2})$", re.MULTILINE)


def read_document(slug: str) -> LegalDocOut:
    if slug not in SLUGS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")
    content = (DOCS_DIR / f"{slug}.md").read_text(encoding="utf-8")
    title = TITLE_RE.search(content)
    revision = REVISION_RE.search(content)
    return LegalDocOut(
        slug=slug,
        title=title.group(1),
        content_md=content,
        revision_date=date.fromisoformat(revision.group(1)),
    )


@router.get("")
async def list_documents() -> list[LegalDocSummary]:
    return [LegalDocSummary(slug=doc.slug, title=doc.title) for doc in map(read_document, SLUGS)]


@router.get("/{slug}")
async def get_document(slug: str) -> LegalDocOut:
    return read_document(slug)
