import uuid

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser
from app.core.errors import not_ready
from app.schemas.search import SearchHit

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def search(
    user: CurrentUser,
    q: str = Query(min_length=2, max_length=200),
    lecture_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
) -> list[SearchHit]:
    not_ready()
