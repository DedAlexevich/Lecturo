from typing import Any

from fastapi import APIRouter

from app.core.errors import not_ready

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/hooks", include_in_schema=False)
async def tusd_hook(body: dict[str, Any]) -> dict[str, Any]:
    not_ready()
