from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select, text

from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep
from app.models import (
    Chapter,
    Lecture,
    LectureStatus,
    SourceType,
    Summary,
    TranscriptSegment,
    UsageEntry,
    UsageSource,
)
from app.pipeline.tasks import enqueue_lecture
from app.schemas.lecture import LectureOut, LocalResultIn
from app.services.local_validation import LocalResultInvalid, validate_local_result
from app.services.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/local-results", tags=["local-results"])

QUOTA_WINDOW = timedelta(days=7)


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_local_result(
    body: LocalResultIn, user: CurrentUser, session: SessionDep
) -> LectureOut:
    settings = get_settings()

    await enforce_rate_limit(
        settings.redis_url,
        f"rate:local-results:{user.id}",
        settings.local_results_rate_limit,
        settings.local_results_rate_window_seconds,
    )

    try:
        validate_local_result(body, settings)
    except LocalResultInvalid as error:
        raise HTTPException(422, str(error)) from error

    await session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"local-results:{user.id}"},
    )
    since = datetime.now(UTC) - QUOTA_WINDOW
    used_count, used_seconds = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(UsageEntry.seconds), 0)).where(
                UsageEntry.user_id == user.id,
                UsageEntry.source == UsageSource.local_embeddings,
                UsageEntry.created_at >= since,
            )
        )
    ).one()
    if (
        used_count >= settings.local_lectures_weekly_count
        or used_seconds + body.duration_sec > settings.local_embeddings_weekly_seconds
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Недельный лимит локальных лекций исчерпан"
        )

    lecture = Lecture(
        owner_id=user.id,
        title=body.title,
        source_type=SourceType.local,
        duration_sec=body.duration_sec,
        language=body.language,
        status=LectureStatus.queued,
        processed_locally=True,
    )
    session.add(lecture)
    await session.flush()
    session.add_all(
        TranscriptSegment(lecture_id=lecture.id, idx=idx, start=s.start, end=s.end, text=s.text)
        for idx, s in enumerate(body.segments)
    )
    session.add_all(
        Chapter(
            lecture_id=lecture.id,
            idx=idx,
            start=c.start,
            end=c.end,
            title=c.title,
            summary=c.summary,
        )
        for idx, c in enumerate(body.chapters)
    )
    if body.summary_md:
        session.add(Summary(lecture_id=lecture.id, content_md=body.summary_md))
    session.add(
        UsageEntry(
            user_id=user.id,
            lecture_id=lecture.id,
            source=UsageSource.local_embeddings,
            seconds=round(body.duration_sec),
        )
    )
    await session.commit()

    try:
        await enqueue_lecture(lecture.id)
    except (OSError, RedisError) as error:
        await session.execute(delete(UsageEntry).where(UsageEntry.lecture_id == lecture.id))
        await session.delete(lecture)
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Очередь недоступна, попробуйте позже"
        ) from error

    return LectureOut.model_validate(lecture)
