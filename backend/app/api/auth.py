from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select, update

from app.core.deps import CurrentUser, SessionDep
from app.core.security import create_access_token
from app.models import AuthTokenKind, User
from app.schemas.user import (
    EmailIn,
    LoginIn,
    PasswordResetIn,
    RegisterIn,
    TelegramLoginIn,
    TokenIn,
    TokenOut,
)
from app.services.auth import authenticate, hash_password, normalize_email, register_user
from app.services.auth_tokens import consume_token, issue_token
from app.services.mail import send_password_reset_mail, send_verification_mail
from app.services.telegram_auth import get_or_create_telegram_user, verify_login_widget

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, session: SessionDep) -> TokenOut:
    if not body.accept_terms:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "accept_terms"),
                    "msg": "Нужно принять условия использования",
                    "type": "value_error",
                }
            ]
        )
    user = await register_user(session, body.email, body.password, body.display_name)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/login")
async def login(body: LoginIn, session: SessionDep) -> TokenOut:
    user = await authenticate(session, body.email, body.password)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/telegram")
async def login_telegram(body: TelegramLoginIn, session: SessionDep) -> TokenOut:
    verify_login_widget(body)
    profile = body.model_dump(exclude={"id", "auth_date", "hash"}, exclude_none=True)
    user = await get_or_create_telegram_user(session, body.id, profile)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/verify-email/request", status_code=status.HTTP_204_NO_CONTENT)
async def request_email_verification(
    user: CurrentUser, session: SessionDep, background: BackgroundTasks
) -> None:
    if not user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У аккаунта нет email")
    if user.email_verified_at is not None:
        return
    token = await issue_token(session, user.id, AuthTokenKind.verify_email)
    background.add_task(send_verification_mail, user.email, token)


@router.post("/verify-email/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_email(body: TokenIn, session: SessionDep) -> None:
    user_id = await consume_token(session, body.token, AuthTokenKind.verify_email)
    await session.execute(
        update(User)
        .where(User.id == user_id, User.email_verified_at.is_(None))
        .values(email_verified_at=datetime.now(UTC))
    )
    await session.commit()


@router.post("/password-reset/request", status_code=status.HTTP_204_NO_CONTENT)
async def request_password_reset(
    body: EmailIn, session: SessionDep, background: BackgroundTasks
) -> None:
    user = await session.scalar(select(User).where(User.email == normalize_email(body.email)))
    if user is None or user.email is None:
        return
    token = await issue_token(session, user.id, AuthTokenKind.reset_password)
    background.add_task(send_password_reset_mail, user.email, token)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(body: PasswordResetIn, session: SessionDep) -> None:
    user_id = await consume_token(session, body.token, AuthTokenKind.reset_password)
    await session.execute(
        update(User).where(User.id == user_id).values(password_hash=hash_password(body.password))
    )
    await session.commit()
