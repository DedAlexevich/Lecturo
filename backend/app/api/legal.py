from fastapi import APIRouter

from app.schemas.legal import LegalDocOut, LegalDocSummary, LegalUpdateOut
from app.services.legal import SLUGS, current_updates, read_document, today

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("")
async def list_documents() -> list[LegalDocSummary]:
    return [LegalDocSummary(slug=doc.slug, title=doc.title) for doc in map(read_document, SLUGS)]


@router.get("/updates")
async def list_updates() -> list[LegalUpdateOut]:
    return current_updates(today())


@router.get("/{slug}")
async def get_document(slug: str) -> LegalDocOut:
    return read_document(slug)
