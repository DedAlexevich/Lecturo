import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse
from redis.exceptions import RedisError
from sqlalchemy import delete, exists, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload
from sqlalchemy.sql.base import ExecutableOption

from app.api.courses import get_own_course
from app.api.shares import shared_with
from app.core.config import get_settings
from app.core.deps import CurrentUser, RequireSubscription, SessionDep
from app.models import (
    Lecture,
    LectureStatus,
    ProcessingStep,
    Quiz,
    SourceType,
    StepName,
    StepStatus,
    User,
    course_lectures,
)
from app.pipeline.download import LinkError, inspect_link, link_key
from app.pipeline.estimate import expected_seconds, remaining_seconds
from app.pipeline.events import publish_status
from app.pipeline.jobs import cancel_lecture_jobs
from app.pipeline.runner import get_step
from app.pipeline.stages import discard_operation_objects, lock_operation_objects
from app.pipeline.tasks import (
    PLANS,
    QUEUE_UNAVAILABLE,
    REGENERATION_STEPS,
    enqueue_lecture,
    enqueue_quiz,
    enqueue_regeneration,
    quiz_job_active,
)
from app.pipeline.video_access import is_valid_signature, signed_audio_url, signed_video_url
from app.schemas.lecture import (
    LectureDetail,
    LectureOut,
    LectureStatusOut,
    LectureUpdate,
    LinkIn,
    LinkLectureOut,
    QuizOut,
    StepOut,
)
from app.services import quota
from app.services.account import lecture_files, remove_files
from app.services.consents import require_ai_transfer_consent
from app.services.rate_limit import enforce_rate_limit, is_rate_limited, reset_rate_limit

router = APIRouter(prefix="/lectures", tags=["lectures"])

VIDEO_FORBIDDEN = "Нет доступа к видео"
AUDIO_FORBIDDEN = "Нет доступа к аудио"
LECTURE_NOT_FOUND = "Лекция не найдена"


async def own_lecture(
    session: AsyncSession,
    lecture_id: uuid.UUID,
    user: User,
    *options: ExecutableOption,
    for_update: bool = False,
) -> Lecture:
    query = select(Lecture).where(Lecture.id == lecture_id, Lecture.owner_id == user.id)
    if options:
        query = query.options(*options)
    if for_update:
        query = query.with_for_update()
    lecture = await session.scalar(query)
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, LECTURE_NOT_FOUND)
    return lecture


async def add_to_course(session: AsyncSession, course_id: uuid.UUID, lecture_id: uuid.UUID) -> None:
    next_position = (
        select(func.coalesce(func.max(course_lectures.c.position) + 1, 0))
        .where(course_lectures.c.course_id == course_id)
        .scalar_subquery()
    )
    await session.execute(
        insert(course_lectures).values(
            course_id=course_id, lecture_id=lecture_id, position=next_position
        )
    )


@router.get("")
async def list_lectures(user: CurrentUser, session: SessionDep) -> list[LectureOut]:
    rows = await session.scalars(
        select(Lecture).where(Lecture.owner_id == user.id).order_by(Lecture.created_at.desc())
    )
    return [LectureOut.model_validate(row) for row in rows]


@router.get("/{lecture_id}")
async def get_lecture(
    lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> LectureDetail:
    lecture = await own_lecture(
        session,
        lecture_id,
        user,
        selectinload(Lecture.steps),
        selectinload(Lecture.segments),
        selectinload(Lecture.chapters),
        selectinload(Lecture.summary),
    )
    video_url = signed_video_url(lecture.id) if lecture.video_path else None
    audio_only = is_audio_only(lecture)
    audio_url = signed_audio_url(lecture.id) if audio_only and lecture.audio_path else None
    steps, eta_sec = progress_of(lecture)
    return LectureDetail.model_validate(lecture).model_copy(
        update={
            "video_url": video_url,
            "audio_only": audio_only,
            "audio_url": audio_url,
            "steps": steps,
            "eta_sec": eta_sec,
        }
    )


def progress_of(lecture: Lecture) -> tuple[list[StepOut], int | None]:
    settings = get_settings()
    plan = PLANS[lecture.source_type]
    steps = [
        StepOut(
            step=step.step,
            status=step.status,
            progress=step.progress,
            error=step.error,
            stage=step.stage,
            expected_sec=rounded(expected_seconds(step.step, lecture.duration_sec, settings)),
        )
        for step in lecture.steps
    ]
    if lecture.status == LectureStatus.ready:
        return steps, None
    known = {step.step for step in steps}
    steps += [
        StepOut(
            step=name,
            status=StepStatus.pending,
            progress=0.0,
            error=None,
            expected_sec=rounded(expected_seconds(name, lecture.duration_sec, settings)),
        )
        for name in plan
        if name not in known
    ]
    if lecture.status == LectureStatus.failed:
        return steps, None
    eta = remaining_seconds(
        plan,
        [(step.step, step.status, step.progress) for step in steps],
        lecture.duration_sec,
        settings,
    )
    return steps, eta


def rounded(value: float | None) -> int | None:
    return None if value is None else round(value)


async def status_of(session: AsyncSession, lecture: Lecture) -> LectureStatusOut:
    steps, eta_sec = progress_of(lecture)
    position = None
    if lecture.status == LectureStatus.queued:
        position = await session.scalar(
            select(func.count())
            .select_from(Lecture)
            .where(Lecture.status == LectureStatus.queued, Lecture.updated_at < lecture.updated_at)
        )
    return LectureStatusOut(
        id=lecture.id,
        status=lecture.status,
        queue_position=position,
        eta_sec=eta_sec,
        steps=steps,
    )


def is_audio_only(lecture: Lecture) -> bool:
    if lecture.source_type != SourceType.upload or lecture.video_expires_at is not None:
        return False
    return any(
        step.step == StepName.video and step.status == StepStatus.done for step in lecture.steps
    )


@router.get("/{lecture_id}/audio")
async def audio_file(
    lecture_id: uuid.UUID, session: SessionDep, expires: str = "", signature: str = ""
) -> FileResponse:
    if not expires.isdecimal() or not is_valid_signature(
        lecture_id, int(expires), signature, None, "audio"
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, AUDIO_FORBIDDEN)
    audio_path = await session.scalar(select(Lecture.audio_path).where(Lecture.id == lecture_id))
    if audio_path is None or not await asyncio.to_thread(Path(audio_path).is_file):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Аудио не найдено")
    return FileResponse(audio_path, media_type="audio/ogg")


@router.get("/{lecture_id}/video-access")
async def video_access(
    lecture_id: uuid.UUID,
    session: SessionDep,
    expires: str = "",
    signature: str = "",
    share: str | None = None,
) -> Response:
    if not expires.isdecimal() or not is_valid_signature(
        lecture_id, int(expires), signature, share
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, VIDEO_FORBIDDEN)
    query = select(Lecture.id).where(Lecture.id == lecture_id, Lecture.video_path.is_not(None))
    if share is not None:
        query = query.where(shared_with(share))
    if await session.scalar(query) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, VIDEO_FORBIDDEN)
    return Response(status_code=status.HTTP_200_OK)


async def find_same_link(session: AsyncSession, user_id: uuid.UUID, url: str) -> Lecture | None:
    key = link_key(url)
    lectures = await session.scalars(
        select(Lecture)
        .where(
            Lecture.owner_id == user_id,
            Lecture.source_type == SourceType.link,
            Lecture.status != LectureStatus.failed,
        )
        .order_by(Lecture.created_at.desc())
    )
    return next(
        (lecture for lecture in lectures if link_key(lecture.source_url or "") == key), None
    )


async def add_existing_to_course(
    session: AsyncSession, course_id: uuid.UUID, lecture_id: uuid.UUID
) -> None:
    in_course = await session.scalar(
        select(
            exists().where(
                course_lectures.c.course_id == course_id,
                course_lectures.c.lecture_id == lecture_id,
            )
        )
    )
    if not in_course:
        await add_to_course(session, course_id, lecture_id)


@router.post(
    "/link",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {"model": LinkLectureOut},
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Слишком много ссылок подряд"},
    },
)
async def add_link(
    body: LinkIn, user: CurrentUser, session: SessionDep, response: Response
) -> LinkLectureOut:
    require_ai_transfer_consent(user)
    settings = get_settings()
    await enforce_rate_limit(
        settings.redis_url,
        f"rate:lecture-link:{user.id}",
        settings.link_rate_limit,
        settings.link_rate_window_seconds,
        "Слишком много ссылок подряд, попробуйте через минуту",
    )
    url = str(body.url)
    if body.course_id is not None:
        await get_own_course(session, body.course_id, user)
    if (same := await find_same_link(session, user.id, url)) is not None:
        if body.course_id is not None:
            await add_existing_to_course(session, body.course_id, same.id)
        existing = LinkLectureOut.model_validate(same).model_copy(update={"existing": True})
        await session.commit()
        response.status_code = status.HTTP_200_OK
        return existing
    await session.commit()
    try:
        async with asyncio.timeout(settings.link_inspect_timeout_seconds):
            link = await inspect_link(url)
    except LinkError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except TimeoutError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Видео по ссылке не ответило вовремя, попробуйте позже",
        ) from error

    lecture = Lecture(
        owner_id=user.id,
        title=(body.title or link.title or "Лекция по ссылке")[:300],
        source_type=SourceType.link,
        source_url=url,
        embed_url=link.embed_url,
        duration_sec=link.duration,
        status=LectureStatus.queued,
    )
    session.add(lecture)
    await session.flush()
    if body.course_id is not None:
        await add_to_course(session, body.course_id, lecture.id)
    waiting = await quota.hold_if_over_quota(session, user, lecture)
    await session.commit()
    await session.refresh(lecture)
    if waiting:
        await publish_status(lecture.id, user.id, lecture.status)
        return LinkLectureOut.model_validate(lecture)

    try:
        await enqueue_lecture(lecture.id)
    except (OSError, RedisError) as error:
        lecture.status = LectureStatus.failed
        await session.commit()
        await publish_status(lecture.id, user.id, LectureStatus.failed, QUEUE_UNAVAILABLE)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error
    return LinkLectureOut.model_validate(lecture)


@router.patch("/{lecture_id}")
async def update_lecture(
    lecture_id: uuid.UUID, body: LectureUpdate, user: CurrentUser, session: SessionDep
) -> LectureOut:
    lecture = await own_lecture(session, lecture_id, user)
    lecture.title = body.title
    await session.commit()
    await session.refresh(lecture)
    return LectureOut.model_validate(lecture)


@router.delete("/{lecture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lecture(lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    lecture = await own_lecture(session, lecture_id, user, for_update=True)
    started = await session.scalar(
        select(exists().where(ProcessingStep.lecture_id == lecture_id, ProcessingStep.attempts > 0))
    )
    if not started and lecture.status in (LectureStatus.queued, LectureStatus.waiting_quota):
        await quota.refund_lecture(session, lecture_id)
    files = lecture_files(lecture_id, [lecture.video_path, lecture.audio_path])
    stt_objects = await lock_operation_objects(session, [lecture_id])
    await session.execute(delete(Lecture).where(Lecture.id == lecture_id))
    await session.commit()

    await cancel_lecture_jobs([lecture_id])
    await asyncio.to_thread(remove_files, files)
    await discard_operation_objects(stt_objects)


@router.get("/{lecture_id}/status")
async def get_status(
    lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> LectureStatusOut:
    lecture = await own_lecture(
        session,
        lecture_id,
        user,
        load_only(
            Lecture.id,
            Lecture.status,
            Lecture.source_type,
            Lecture.duration_sec,
            Lecture.updated_at,
        ),
        selectinload(Lecture.steps),
    )
    return await status_of(session, lecture)


@router.post("/{lecture_id}/retry")
async def retry(lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> LectureStatusOut:
    queued = await session.scalar(
        update(Lecture)
        .where(
            Lecture.id == lecture_id,
            Lecture.owner_id == user.id,
            Lecture.status == LectureStatus.failed,
        )
        .values(status=LectureStatus.queued)
        .returning(Lecture.id)
    )
    if queued is None:
        await own_lecture(session, lecture_id, user, load_only(Lecture.id))
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Перезапустить можно только упавшую обработку"
        )
    await session.execute(
        update(ProcessingStep)
        .where(ProcessingStep.lecture_id == lecture_id, ProcessingStep.status == StepStatus.failed)
        .values(status=StepStatus.pending, progress=0.0, stage=None, error=None)
    )
    await session.commit()

    try:
        await enqueue_lecture(lecture_id)
    except (OSError, RedisError) as error:
        await session.execute(
            update(Lecture).where(Lecture.id == lecture_id).values(status=LectureStatus.failed)
        )
        await session.commit()
        await publish_status(lecture_id, user.id, LectureStatus.failed, QUEUE_UNAVAILABLE)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error

    lecture = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id)
        .options(selectinload(Lecture.steps))
        .execution_options(populate_existing=True)
    )
    return await status_of(session, lecture)


@router.post("/{lecture_id}/regenerate-summary", status_code=status.HTTP_202_ACCEPTED)
async def regenerate_summary(
    lecture_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> LectureStatusOut:
    lecture = await own_lecture(session, lecture_id, user, for_update=True)
    if lecture.status != LectureStatus.ready:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Пересоздать главы и конспект можно у обработанной лекции, пока она не обрабатывается",
        )
    if lecture.processed_locally or lecture.source_type == SourceType.local:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Лекция обработана на устройстве, пересоздать главы и конспект на сервере нельзя",
        )
    require_ai_transfer_consent(user)
    settings = get_settings()
    limit_key = f"rate:regenerate-summary:{lecture_id}"
    try:
        limited = await is_rate_limited(
            settings.redis_url,
            limit_key,
            1,
            settings.regenerate_summary_rate_window_seconds,
        )
    except (OSError, RedisError) as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error
    if limited:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Главы и конспект уже пересоздавались недавно, повторите через несколько минут",
        )
    for name in REGENERATION_STEPS:
        step = await get_step(session, lecture.id, name)
        step.status = StepStatus.pending
        step.progress = 0.0
        step.stage = None
        step.error = None
    lecture.status = LectureStatus.processing
    await session.commit()
    await publish_status(lecture.id, user.id, LectureStatus.processing)

    try:
        await enqueue_regeneration(lecture.id)
    except (OSError, RedisError) as error:
        await session.execute(
            update(ProcessingStep)
            .where(
                ProcessingStep.lecture_id == lecture_id,
                ProcessingStep.step.in_(REGENERATION_STEPS),
            )
            .values(status=StepStatus.done, progress=1.0)
        )
        lecture.status = LectureStatus.ready
        await session.commit()
        await reset_rate_limit(settings.redis_url, limit_key)
        await publish_status(lecture.id, user.id, LectureStatus.ready, QUEUE_UNAVAILABLE)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error

    refreshed = await session.scalar(
        select(Lecture)
        .where(Lecture.id == lecture_id)
        .options(selectinload(Lecture.steps))
        .execution_options(populate_existing=True)
    )
    return await status_of(session, refreshed)


@router.post("/{lecture_id}/quiz", status_code=status.HTTP_202_ACCEPTED)
async def create_quiz(
    lecture_id: uuid.UUID, user: RequireSubscription, session: SessionDep
) -> None:
    require_ai_transfer_consent(user)
    lecture = await own_lecture(session, lecture_id, user, for_update=True)
    if lecture.status != LectureStatus.ready:
        raise HTTPException(status.HTTP_409_CONFLICT, "Квиз можно сделать, когда лекция обработана")
    step = await get_step(session, lecture.id, StepName.quiz)
    try:
        if step.status in (StepStatus.pending, StepStatus.running) and await quiz_job_active(
            lecture.id
        ):
            return
        step.status = StepStatus.pending
        step.progress = 0.0
        step.error = None
        await session.commit()
        await enqueue_quiz(lecture.id)
    except (OSError, RedisError) as error:
        step.status = StepStatus.failed
        step.error = QUEUE_UNAVAILABLE
        await session.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error


@router.get("/{lecture_id}/quiz")
async def get_quiz(
    lecture_id: uuid.UUID, user: RequireSubscription, session: SessionDep
) -> QuizOut:
    await own_lecture(session, lecture_id, user, load_only(Lecture.id))
    quiz = await session.scalar(select(Quiz).where(Quiz.lecture_id == lecture_id))
    if quiz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Квиз ещё не готов")
    return QuizOut.model_validate(quiz)
