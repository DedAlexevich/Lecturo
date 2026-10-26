from fastapi import APIRouter

from app.core.errors import not_ready
from app.schemas.legal import LegalDocOut, LegalDocSummary

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("")
async def list_documents() -> list[LegalDocSummary]:
    not_ready()


@router.get("/{slug}")
async def get_document(slug: str) -> LegalDocOut:
    not_ready()
