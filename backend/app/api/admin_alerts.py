from fastapi import APIRouter, Depends, status

from app.core.deps import AdminUser, SessionDep, get_admin_user
from app.schemas.admin_alerts import AlertSettingsIn, AlertSettingsOut
from app.services import admin_alerts

router = APIRouter(prefix="/admin/alerts", tags=["admin"], dependencies=[Depends(get_admin_user)])


@router.get("/settings")
async def get_alert_settings(admin: AdminUser, session: SessionDep) -> AlertSettingsOut:
    return await admin_alerts.get_settings(session, admin)


@router.put("/settings")
async def put_alert_settings(
    body: AlertSettingsIn, admin: AdminUser, session: SessionDep
) -> AlertSettingsOut:
    return await admin_alerts.save_settings(session, admin, body)


@router.post(
    "/test",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_409_CONFLICT: {"description": "Telegram не привязан или бот не запущен"}
    },
)
async def send_test_alert(admin: AdminUser, session: SessionDep) -> None:
    await admin_alerts.send_test(session, admin)
