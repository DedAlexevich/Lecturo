from fastapi import APIRouter, status

from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep
from app.models import AuthProvider
from app.schemas.user import (
    AccountDeleteIn,
    EmailIdentityIn,
    PasswordChangeIn,
    ProfileUpdateIn,
    TelegramLoginIn,
    UserOut,
)
from app.services import identities
from app.services.account import (
    change_password,
    confirm_deletion,
    delete_account,
    update_display_name,
)
from app.services.rate_limit import enforce_rate_limit
from app.services.telegram_auth import verify_login_widget

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
async def get_me(user: CurrentUser, session: SessionDep) -> UserOut:
    return await identities.user_out(session, user)


@router.patch("")
async def update_me(body: ProfileUpdateIn, user: CurrentUser, session: SessionDep) -> UserOut:
    await update_display_name(session, user, body.display_name)
    return await identities.user_out(session, user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    body: PasswordChangeIn, user: CurrentUser, session: SessionDep
) -> None:
    settings = get_settings()
    await enforce_rate_limit(
        settings.redis_url,
        f"rate:password-change:{user.id}",
        settings.password_change_rate_limit,
        settings.password_change_rate_window_seconds,
    )
    await change_password(session, user, body.current_password, body.new_password)


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(body: AccountDeleteIn, user: CurrentUser, session: SessionDep) -> None:
    settings = get_settings()
    await enforce_rate_limit(
        settings.redis_url,
        f"rate:account-delete:{user.id}",
        settings.account_delete_rate_limit,
        settings.account_delete_rate_window_seconds,
    )
    await confirm_deletion(session, user, body)
    await delete_account(session, user)


@router.post("/identities/telegram")
async def link_telegram(body: TelegramLoginIn, user: CurrentUser, session: SessionDep) -> UserOut:
    verify_login_widget(body)
    profile = body.model_dump(exclude={"id", "auth_date", "hash"}, exclude_none=True)
    await identities.link_telegram(session, user, body.id, profile)
    return await identities.user_out(session, user)


@router.post("/identities/email")
async def link_email(body: EmailIdentityIn, user: CurrentUser, session: SessionDep) -> UserOut:
    await identities.link_email(session, user, body)
    return await identities.user_out(session, user)


@router.delete("/identities/{provider}")
async def unlink_identity(
    provider: AuthProvider, user: CurrentUser, session: SessionDep
) -> UserOut:
    await identities.unlink_identity(session, user, provider)
    return await identities.user_out(session, user)


@router.post("/consents/ai-transfer")
async def accept_ai_transfer(user: CurrentUser, session: SessionDep) -> UserOut:
    await identities.accept_ai_transfer(session, user)
    return await identities.user_out(session, user)
