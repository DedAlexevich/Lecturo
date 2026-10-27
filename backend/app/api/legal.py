from fastapi import APIRouter

from app.schemas.legal import LegalDocOut, LegalDocSummary
from app.services.legal import SLUGS, read_document

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("")
async def list_documents() -> list[LegalDocSummary]:
    return [LegalDocSummary(slug=doc.slug, title=doc.title) for doc in map(read_document, SLUGS)]


@router.get("/{slug}")
async def get_document(slug: str) -> LegalDocOut:
    return read_document(slug)
