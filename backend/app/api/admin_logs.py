import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.deps import AdminUser, SessionDep, get_admin_user
from app.models import AdminAction, BusinessEventKind, LectureStatus
from app.schemas.admin_logs import (
    BusinessEventOut,
    BusinessEventsPage,
    LogLineOut,
    LogTailOut,
    ProcessingErrorOut,
    ProcessingErrorsPage,
)
from app.services import admin_events, admin_logs, business_events
from app.services.admin import record_action

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_admin_user)])

LOG_RESPONSES = {status.HTTP_404_NOT_FOUND: {"description": admin_logs.LOG_UNAVAILABLE}}


def lines_out(lines: list[admin_logs.LogLine]) -> list[dict]:
    return [{"level": line.level, "text": line.text} for line in lines]


def sse(event: str, data: object, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/logs/{service}", responses=LOG_RESPONSES)
async def get_log(
    service: admin_logs.LogService,
    level: Annotated[admin_logs.LogLevel | None, Query()] = None,
    q: Annotated[str, Query(max_length=200)] = "",
    lines: Annotated[int, Query(ge=1, le=admin_logs.MAX_LINES)] = admin_logs.DEFAULT_LINES,
) -> LogTailOut:
    try:
        tail = await admin_logs.read_tail(service, lines, level, q)
    except admin_logs.LogUnavailable as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, admin_logs.LOG_UNAVAILABLE) from error
    return LogTailOut(
        service=service,
        lines=[LogLineOut(level=line.level, text=line.text) for line in tail.lines],
        offset=tail.offset,
        size=tail.size,
        modified_at=tail.modified_at,
    )


async def stream_events(
    request: Request,
    service: admin_logs.LogService,
    level: admin_logs.LogLevel | None,
    q: str,
    offset: int | None,
) -> AsyncIterator[str]:
    limit = get_settings().log_stream_limit
    if not admin_logs.stream_slots.acquire(limit):
        yield sse("error", {"detail": admin_logs.TOO_MANY_STREAMS})
        return
    started = time.monotonic()
    last_sent = started
    try:
        async for chunk in admin_logs.follow(service, level, q, offset):
            now = time.monotonic()
            if await request.is_disconnected():
                return
            if chunk is not None:
                last_sent = now
                yield sse(
                    "lines",
                    {"lines": lines_out(chunk.lines), "restarted": chunk.restarted},
                    chunk.offset,
                )
            elif now - last_sent >= admin_logs.STREAM_HEARTBEAT_SECONDS:
                last_sent = now
                yield ": ping\n\n"
            if now - started >= admin_logs.STREAM_MAX_SECONDS:
                yield sse("end", {"detail": "limit"})
                return
    except admin_logs.LogUnavailable:
        yield sse("error", {"detail": admin_logs.LOG_UNAVAILABLE})
    finally:
        admin_logs.stream_slots.release()


@router.get("/logs/{service}/stream", responses=LOG_RESPONSES)
async def stream_log(
    service: admin_logs.LogService,
    request: Request,
    actor: AdminUser,
    session: SessionDep,
    level: Annotated[admin_logs.LogLevel | None, Query()] = None,
    q: Annotated[str, Query(max_length=200)] = "",
    offset: Annotated[int | None, Query(ge=0)] = None,
) -> StreamingResponse:
    try:
        await asyncio.to_thread(admin_logs.ensure_available, service)
    except admin_logs.LogUnavailable as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, admin_logs.LOG_UNAVAILABLE) from error
    if offset is None:
        record_action(
            session,
            actor,
            AdminAction.logs_stream_started,
            "log",
            service.value,
            service.value,
            {"level": level, "query": q},
        )
        await session.commit()
    return StreamingResponse(
        stream_events(request, service, level, q, offset),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/processing-errors")
async def get_processing_errors(
    session: SessionDep,
    only_failed: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProcessingErrorsPage:
    total, rows = await admin_events.failed_steps_page(session, only_failed, limit, offset)
    items = [
        ProcessingErrorOut(
            lecture_id=lecture.id,
            lecture_title=lecture.title,
            lecture_status=lecture.status,
            step=step.step,
            error=admin_events.masked_error(step.error),
            attempts=step.attempts,
            failed_at=admin_events.failed_at(step),
            user_id=user.id if user else None,
            user_label=(user.email or user.display_name or str(user.id)) if user else "",
            can_retry=lecture.status == LectureStatus.failed,
        )
        for step, lecture, user in rows
    ]
    return ProcessingErrorsPage(total=total, items=items)


@router.post(
    "/processing-errors/{lecture_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": admin_events.LECTURE_NOT_FOUND},
        status.HTTP_409_CONFLICT: {"description": admin_events.RETRY_ONLY_FAILED},
    },
)
async def retry_processing(lecture_id: uuid.UUID, actor: AdminUser, session: SessionDep) -> None:
    await admin_events.retry_lecture(session, actor, lecture_id)


@router.get("/events")
async def get_events(
    session: SessionDep,
    kind: Annotated[BusinessEventKind | None, Query()] = None,
    user_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BusinessEventsPage:
    total, events = await business_events.events_page(session, kind, user_id, limit, offset)
    return BusinessEventsPage(
        total=total, items=[BusinessEventOut.model_validate(event) for event in events]
    )
