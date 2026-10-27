import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.deps import CurrentUser, SessionDep
from app.core.security import create_access_token
from app.models import AuthToken, AuthTokenKind, User
from app.schemas.user import (
    EmailIn,
    LoginIn,
    PasswordResetIn,
    ProvidersOut,
    RegisterIn,
    TelegramSignupIn,
    TokenIn,
    TokenOut,
    VkCallbackIn,
    VkStartIn,
    VkStartOut,
)
from app.services.auth import authenticate, hash_password, normalize_email, register_user
from app.services.auth_tokens import consume_token, issue_token
from app.services.consents import require_signup_consents
from app.services.mail import send_password_reset_mail, send_verification_mail
from app.services.rate_limit import enforce_mail_rate_limit, enforce_rate_limit
from app.services.telegram_auth import (
    TELEGRAM_PROFILE_FIELDS,
    get_or_create_telegram_user,
    verify_login_widget,
)
from app.services.vk_auth import (
    VkClientDep,
    complete_flow,
    get_or_create_vk_user,
    start_flow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, session: SessionDep) -> TokenOut:
    require_signup_consents(body.accept_terms, body.accept_personal_data)
    user = await register_user(session, body.email, body.password, body.display_name)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/login")
async def login(body: LoginIn, session: SessionDep) -> TokenOut:
    user = await authenticate(session, body.email, body.password)
    return TokenOut(access_token=create_access_token(user.id))


@router.post(
    "/telegram",
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "Новому пользователю нужны оба согласия"}
    },
)
async def login_telegram(body: TelegramSignupIn, session: SessionDep) -> TokenOut:
    verify_login_widget(body)
    profile = body.model_dump(include=TELEGRAM_PROFILE_FIELDS, exclude_none=True)
    user = await get_or_create_telegram_user(
        session, body.id, profile, body.accept_terms, body.accept_personal_data
    )
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/providers")
async def providers() -> ProvidersOut:
    return ProvidersOut(vk=get_settings().vk_enabled)


@router.post(
    "/vk/start",
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Слишком много попыток входа"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Вход через VK не настроен"},
    },
)
async def start_vk_login(body: VkStartIn, request: Request) -> VkStartOut:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        settings.redis_url,
        f"rate:vk-start:{ip}",
        settings.vk_start_rate_limit,
        settings.vk_start_rate_window_seconds,
    )
    url, nonce = await start_flow(
        settings,
        accept_terms=body.accept_terms,
        accept_personal_data=body.accept_personal_data,
    )
    return VkStartOut(url=url, nonce=nonce)


@router.post(
    "/vk/callback",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Сессия входа не найдена или устарела"},
        status.HTTP_401_UNAUTHORIZED: {"description": "VK отклонил вход"},
        status.HTTP_403_FORBIDDEN: {"description": "Новому пользователю нужны оба согласия"},
        status.HTTP_502_BAD_GATEWAY: {"description": "VK недоступен"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Вход через VK не настроен"},
    },
)
async def login_vk(body: VkCallbackIn, session: SessionDep, client: VkClientDep) -> TokenOut:
    vk_id, profile, flow = await complete_flow(
        get_settings(), client, body.code, body.state, body.device_id, body.nonce
    )
    user = await get_or_create_vk_user(
        session, vk_id, profile, flow["accept_terms"], flow["accept_personal_data"]
    )
    return TokenOut(access_token=create_access_token(user.id))


@router.post(
    "/verify-email/request",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Слишком много запросов писем"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Хранилище лимитов недоступно"},
    },
)
async def request_email_verification(
    user: CurrentUser, session: SessionDep, background: BackgroundTasks, request: Request
) -> None:
    if not user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У аккаунта нет email")
    await enforce_mail_rate_limit(request, f"verify:{user.id}")
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


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Слишком много запросов писем"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Хранилище лимитов недоступно"},
    },
)
async def request_password_reset(
    body: EmailIn, background: BackgroundTasks, request: Request
) -> None:
    email = normalize_email(body.email)
    await enforce_mail_rate_limit(request, f"reset:{email}", per_ip=True)
    background.add_task(issue_and_send_password_reset, email)


async def issue_and_send_password_reset(email: str) -> None:
    try:
        async with SessionLocal() as session:
            user = await session.scalar(select(User).where(User.email == email))
            if user is None or user.email is None:
                return
            token = await issue_token(session, user.id, AuthTokenKind.reset_password)
        await send_password_reset_mail(user.email, token)
    except Exception:
        logger.exception("Не удалось выдать и отправить ссылку сброса пароля")


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(body: PasswordResetIn, session: SessionDep) -> None:
    user_id = await consume_token(session, body.token, AuthTokenKind.reset_password)
    await session.execute(
        update(User).where(User.id == user_id).values(password_hash=hash_password(body.password))
    )
    await session.execute(
        delete(AuthToken).where(AuthToken.user_id == user_id, AuthToken.used_at.is_(None))
    )
    await session.commit()
