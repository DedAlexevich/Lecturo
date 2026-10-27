import uuid

from fastapi import APIRouter, status

from app.core.deps import RequireSubscription
from app.core.errors import not_ready
from app.schemas.lecture import ExamSheetOut

router = APIRouter(prefix="/courses/{course_id}/exam-sheet", tags=["exam"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_exam_sheet(course_id: uuid.UUID, user: RequireSubscription) -> None:
    not_ready()


@router.get("")
async def get_exam_sheet(course_id: uuid.UUID, user: RequireSubscription) -> ExamSheetOut:
    not_ready()
