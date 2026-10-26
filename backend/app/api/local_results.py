from fastapi import APIRouter, status

from app.core.deps import CurrentUser
from app.core.errors import not_ready
from app.schemas.lecture import LectureOut, LocalResultIn

router = APIRouter(prefix="/local-results", tags=["local-results"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_local_result(body: LocalResultIn, user: CurrentUser) -> LectureOut:
    not_ready()
