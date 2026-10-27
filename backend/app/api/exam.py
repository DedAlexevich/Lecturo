import uuid

from fastapi import APIRouter, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import select

from app.api.courses import get_own_course
from app.core.deps import RequireSubscription, SessionDep
from app.models import ExamSheet
from app.pipeline.exam import enqueue_exam_sheet, exam_sheet_in_progress, load_course_notes
from app.schemas.lecture import ExamSheetOut
from app.services.consents import require_ai_transfer_consent

router = APIRouter(prefix="/courses/{course_id}/exam-sheet", tags=["exam"])

QUEUE_UNAVAILABLE = "Очередь недоступна, попробуйте позже"


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_exam_sheet(
    course_id: uuid.UUID, user: RequireSubscription, session: SessionDep
) -> None:
    await get_own_course(session, course_id, user)
    require_ai_transfer_consent(user)
    if not await load_course_notes(session, course_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "no_summaries", "message": "В курсе нет лекций с готовым конспектом"},
        )
    try:
        await enqueue_exam_sheet(course_id)
    except (OSError, RedisError) as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error


@router.get("")
async def get_exam_sheet(
    course_id: uuid.UUID, user: RequireSubscription, session: SessionDep
) -> ExamSheetOut:
    await get_own_course(session, course_id, user)
    sheet = await session.scalar(select(ExamSheet).where(ExamSheet.course_id == course_id))
    if sheet is not None:
        return ExamSheetOut(course_id=course_id, **sheet.content)
    if await exam_sheet_in_progress(course_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "exam_sheet_processing", "message": "Памятка ещё готовится"},
        )
    raise HTTPException(
        status.HTTP_404_NOT_FOUND,
        {"code": "exam_sheet_not_found", "message": "Памятки по курсу пока нет"},
    )
