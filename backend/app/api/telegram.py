from fastapi import APIRouter, status

from app.core.deps import SessionDep
from app.core.security import create_access_token
from app.schemas.user import TelegramWebAppIn, TokenOut
from app.services.telegram_auth import get_or_create_telegram_user, verify_webapp_init_data

router = APIRouter(prefix="/auth/telegram-webapp", tags=["telegram"])


@router.post(
    "",
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "Новому пользователю нужны оба согласия"}
    },
)
async def login_webapp(body: TelegramWebAppIn, session: SessionDep) -> TokenOut:
    telegram_user = verify_webapp_init_data(body.init_data)
    profile = {
        key: value for key, value in telegram_user.items() if key != "id" and value is not None
    }
    user = await get_or_create_telegram_user(
        session,
        telegram_user["id"],
        profile,
        body.accept_terms,
        body.accept_personal_data,
    )
    return TokenOut(access_token=create_access_token(user.id, user.token_version))
