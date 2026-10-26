from fastapi import APIRouter, status

from app.core.deps import CurrentUser
from app.core.errors import not_ready
from app.schemas.user import (
    EmailIn,
    LoginIn,
    PasswordResetIn,
    RegisterIn,
    TelegramLoginIn,
    TokenIn,
    TokenOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn) -> TokenOut:
    not_ready()


@router.post("/login")
async def login(body: LoginIn) -> TokenOut:
    not_ready()


@router.post("/telegram")
async def login_telegram(body: TelegramLoginIn) -> TokenOut:
    not_ready()


@router.post("/verify-email/request", status_code=status.HTTP_204_NO_CONTENT)
async def request_email_verification(user: CurrentUser) -> None:
    not_ready()


@router.post("/verify-email/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_email(body: TokenIn) -> None:
    not_ready()


@router.post("/password-reset/request", status_code=status.HTTP_204_NO_CONTENT)
async def request_password_reset(body: EmailIn) -> None:
    not_ready()


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(body: PasswordResetIn) -> None:
    not_ready()
