import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.core.deps import SessionDep
from app.schemas.zoomer import ZoomerClipOut
from app.services import zoomer

router = APIRouter(prefix="/zoomer", tags=["zoomer"])


@router.get("/videos")
async def list_zoomer_clips(session: SessionDep) -> list[ZoomerClipOut]:
    return await zoomer.public_clips(session)


@router.get("/videos/{video_id}/access", include_in_schema=False)
async def zoomer_file_access(video_id: uuid.UUID, session: SessionDep) -> Response:
    if not await zoomer.is_public(session, video_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, zoomer.NOT_FOUND)
    return Response(status_code=status.HTTP_200_OK)
