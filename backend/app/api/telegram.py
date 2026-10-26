from fastapi import APIRouter

from app.core.errors import not_ready
from app.schemas.user import TelegramWebAppIn, TokenOut

router = APIRouter(prefix="/auth/telegram-webapp", tags=["telegram"])


@router.post("")
async def login_webapp(body: TelegramWebAppIn) -> TokenOut:
    not_ready()
