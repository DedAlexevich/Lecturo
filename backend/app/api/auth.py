from fastapi import APIRouter, HTTPException, status

from app.core.deps import CurrentUser, SessionDep
from app.core.errors import not_ready
from app.core.security import create_access_token
from app.schemas.user import (
    EmailIn,
    LoginIn,
    PasswordResetIn,
    RegisterIn,
    TelegramLoginIn,
    TokenIn,
    TokenOut,
)
from app.services.auth import authenticate, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, session: SessionDep) -> TokenOut:
    if not body.accept_terms:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Нужно принять условия использования"
        )
    user = await register_user(session, body.email, body.password, body.display_name)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/login")
async def login(body: LoginIn, session: SessionDep) -> TokenOut:
    user = await authenticate(session, body.email, body.password)
    return TokenOut(access_token=create_access_token(user.id))


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
