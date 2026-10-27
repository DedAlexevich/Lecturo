import uuid

from fastapi import APIRouter, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import select

from app.api.courses import get_own_course
from app.core.config import get_settings
from app.core.deps import RequireSubscription, SessionDep
from app.models import ExamSheet
from app.pipeline.exam import (
    clear_exam_sheet_failure,
    course_note_ids,
    enqueue_exam_sheet,
    exam_sheet_failed,
    exam_sheet_in_progress,
    is_outdated,
    load_course_notes,
)
from app.schemas.lecture import ExamSheetOut
from app.services.consents import require_ai_transfer_consent
from app.services.rate_limit import is_rate_limited, reset_rate_limit

router = APIRouter(prefix="/courses/{course_id}/exam-sheet", tags=["exam"])

QUEUE_UNAVAILABLE = "Очередь недоступна, попробуйте позже"


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    responses={status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Памятка собиралась недавно"}},
)
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
    settings = get_settings()
    limit_key = f"rate:exam-sheet:{course_id}"
    try:
        limited = await is_rate_limited(
            settings.redis_url, limit_key, 1, settings.exam_sheet_rate_window_seconds
        )
    except (OSError, RedisError) as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error
    if limited:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Памятка уже собиралась недавно, повторите через несколько минут",
        )
    try:
        await clear_exam_sheet_failure(course_id)
        await enqueue_exam_sheet(course_id)
    except (OSError, RedisError) as error:
        await reset_rate_limit(settings.redis_url, limit_key)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error


@router.get("")
async def get_exam_sheet(
    course_id: uuid.UUID, user: RequireSubscription, session: SessionDep
) -> ExamSheetOut:
    await get_own_course(session, course_id, user)
    sheet = await session.scalar(select(ExamSheet).where(ExamSheet.course_id == course_id))
    try:
        processing = await exam_sheet_in_progress(course_id)
        failed = not processing and sheet is None and await exam_sheet_failed(course_id)
    except (OSError, RedisError) as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error
    if sheet is not None:
        return ExamSheetOut(
            course_id=course_id,
            tickets=sheet.content["tickets"],
            definitions=sheet.content["definitions"],
            cheatsheet_md=sheet.content["cheatsheet_md"],
            outdated=is_outdated(sheet.content, await course_note_ids(session, course_id)),
            processing=processing,
        )
    if processing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "exam_sheet_processing", "message": "Памятка ещё готовится"},
        )
    if failed:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "exam_sheet_failed", "message": "Не удалось собрать памятку"},
        )
    raise HTTPException(
        status.HTTP_404_NOT_FOUND,
        {"code": "exam_sheet_not_found", "message": "Памятки по курсу пока нет"},
    )
