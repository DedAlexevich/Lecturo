from fastapi import APIRouter
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.schemas.admin_backups import MaintenanceOut
from app.services import maintenance

router = APIRouter(tags=["health"])

OPEN_PREFIXES = ("/api/v1/health", "/api/v1/maintenance", "/api/v1/admin/")


@router.get("/maintenance")
async def get_maintenance() -> MaintenanceOut:
    active = await maintenance.is_active()
    return MaintenanceOut(active=active, message=maintenance.MAINTENANCE_MESSAGE if active else "")


class MaintenanceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        blocked = (
            scope["type"] == "http"
            and path.startswith("/api/")
            and not path.startswith(OPEN_PREFIXES)
            and await maintenance.is_active()
        )
        if not blocked:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"detail": maintenance.MAINTENANCE_MESSAGE, "maintenance": True},
            status_code=503,
            headers={"Retry-After": "30"},
        )
        await response(scope, receive, send)
