from fastapi import APIRouter, status

from app.core.deps import CurrentUser
from app.core.errors import not_ready
from app.schemas.share import ComplaintIn, PublicShareOut, ShareIn, ShareOut

router = APIRouter(tags=["shares"])


@router.post("/shares", status_code=status.HTTP_201_CREATED)
async def create_share(body: ShareIn, user: CurrentUser) -> ShareOut:
    not_ready()


@router.get("/shares")
async def list_shares(user: CurrentUser) -> list[ShareOut]:
    not_ready()


@router.delete("/shares/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(token: str, user: CurrentUser) -> None:
    not_ready()


@router.get("/public/{token}")
async def get_public(token: str) -> PublicShareOut:
    not_ready()


@router.post("/public/{token}/complaints", status_code=status.HTTP_204_NO_CONTENT)
async def complain(token: str, body: ComplaintIn) -> None:
    not_ready()
