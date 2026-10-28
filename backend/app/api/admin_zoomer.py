import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from redis.exceptions import RedisError

from app.core.deps import AdminUser, SessionDep, get_admin_user
from app.models import AdminAction, ZoomerVideo, ZoomerVideoStatus
from app.pipeline.zoomer import enqueue_zoomer_video
from app.schemas.zoomer import ZoomerOrderIn, ZoomerVideoOut, ZoomerVideoPatch
from app.services import zoomer
from app.services.admin import record_action

router = APIRouter(prefix="/admin/zoomer", tags=["admin"], dependencies=[Depends(get_admin_user)])

QUEUE_UNAVAILABLE = "Очередь обработки недоступна, попробуйте позже"
NOT_FOUND_RESPONSE = {status.HTTP_404_NOT_FOUND: {"description": zoomer.NOT_FOUND}}


def fail(error: zoomer.ZoomerError) -> HTTPException:
    return HTTPException(error.code, error.message)


@router.get("/videos")
async def list_zoomer_videos(session: SessionDep) -> list[ZoomerVideoOut]:
    return [zoomer.video_out(video) for video in await zoomer.list_videos(session)]


@router.post(
    "/videos",
    status_code=status.HTTP_201_CREATED,
    responses={
        413: {"description": "Файл слишком большой"},
        422: {"description": zoomer.WRONG_TYPE},
        503: {"description": QUEUE_UNAVAILABLE},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "video/mp4": {"schema": {"type": "string", "format": "binary"}},
                "video/webm": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
)
async def upload_zoomer_video(
    request: Request,
    actor: AdminUser,
    session: SessionDep,
    title: Annotated[str, Query(min_length=1, max_length=120)],
    source: Annotated[str, Query(min_length=3, max_length=500)],
) -> ZoomerVideoOut:
    title, source = title.strip(), source.strip()
    if not title or len(source) < 3:
        raise HTTPException(422, "Укажите название, источник и лицензию")
    video_id = uuid.uuid4()
    incoming = zoomer.incoming_file(video_id)
    try:
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > zoomer.upload_limit():
            raise zoomer.too_large()
        container = await zoomer.save_upload(request.stream(), incoming)
        info = await zoomer.inspect_clip(incoming, container)
    except zoomer.ZoomerError as error:
        await asyncio.to_thread(incoming.unlink, missing_ok=True)
        record_action(
            session,
            actor,
            AdminAction.zoomer_video_rejected,
            "zoomer_video",
            None,
            title,
            {"error": error.message},
        )
        await session.commit()
        raise fail(error) from error
    video = ZoomerVideo(
        id=video_id,
        title=title,
        source=source,
        status=ZoomerVideoStatus.processing,
        duration_sec=info.duration,
        width=info.width,
        height=info.height,
        position=await zoomer.next_position(session),
    )
    session.add(video)
    record_action(
        session,
        actor,
        AdminAction.zoomer_video_uploaded,
        "zoomer_video",
        str(video_id),
        title,
        {
            "source": source,
            "container": info.container,
            "duration_sec": round(info.duration, 1),
            "vertical": zoomer.is_vertical(info.width, info.height),
        },
    )
    await session.commit()
    try:
        await enqueue_zoomer_video(video_id)
    except (OSError, RedisError) as error:
        video.status = ZoomerVideoStatus.failed
        video.error = QUEUE_UNAVAILABLE
        await session.commit()
        await asyncio.to_thread(incoming.unlink, missing_ok=True)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, QUEUE_UNAVAILABLE) from error
    return zoomer.video_out(await zoomer.get_video(session, video_id))


@router.patch("/videos/{video_id}", responses=NOT_FOUND_RESPONSE)
async def update_zoomer_video(
    video_id: uuid.UUID, body: ZoomerVideoPatch, actor: AdminUser, session: SessionDep
) -> ZoomerVideoOut:
    try:
        video = await zoomer.get_video(session, video_id)
    except zoomer.ZoomerError as error:
        raise fail(error) from error
    changes = body.model_dump(exclude_none=True)
    if "title" in changes:
        changes["title"] = changes["title"].strip() or video.title
    if "source" in changes:
        changes["source"] = changes["source"].strip() or video.source
    for field, value in changes.items():
        setattr(video, field, value)
    record_action(
        session,
        actor,
        AdminAction.zoomer_video_updated,
        "zoomer_video",
        str(video.id),
        video.title,
        changes,
    )
    await session.commit()
    return zoomer.video_out(await zoomer.get_video(session, video_id))


@router.put("/order", responses={422: {"description": zoomer.ORDER_MISMATCH}})
async def reorder_zoomer_videos(
    body: ZoomerOrderIn, actor: AdminUser, session: SessionDep
) -> list[ZoomerVideoOut]:
    try:
        videos = await zoomer.reorder(session, body.ids)
    except zoomer.ZoomerError as error:
        raise fail(error) from error
    record_action(
        session,
        actor,
        AdminAction.zoomer_videos_reordered,
        "zoomer_video",
        None,
        "",
        {"titles": [video.title for video in videos]},
    )
    await session.commit()
    return [zoomer.video_out(video) for video in await zoomer.list_videos(session)]


@router.delete(
    "/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND_RESPONSE
)
async def delete_zoomer_video(video_id: uuid.UUID, actor: AdminUser, session: SessionDep) -> None:
    try:
        video = await zoomer.get_video(session, video_id)
    except zoomer.ZoomerError as error:
        raise fail(error) from error
    record_action(
        session,
        actor,
        AdminAction.zoomer_video_deleted,
        "zoomer_video",
        str(video.id),
        video.title,
        {"source": video.source},
    )
    await session.delete(video)
    await session.commit()
    await asyncio.to_thread(zoomer.remove_files, video_id)
