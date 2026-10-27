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
    VkCallbackIn,
    VkStartOut,
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
from app.services.vk_auth import VkClientDep, complete_flow, start_flow

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


@router.post(
    "/identities/vk/start",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Вход через VK не настроен"}},
)
async def start_vk_link(user: CurrentUser) -> VkStartOut:
    url, nonce = await start_flow(get_settings(), user_id=user.id)
    return VkStartOut(url=url, nonce=nonce)


@router.post(
    "/identities/vk",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Сессия привязки не найдена или устарела"},
        status.HTTP_401_UNAUTHORIZED: {"description": "VK отклонил вход"},
        status.HTTP_409_CONFLICT: {"description": "VK уже привязан к другому аккаунту"},
        status.HTTP_502_BAD_GATEWAY: {"description": "VK недоступен"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Вход через VK не настроен"},
    },
)
async def link_vk(
    body: VkCallbackIn,
    user: CurrentUser,
    session: SessionDep,
    client: VkClientDep,
) -> UserOut:
    vk_id, profile, _ = await complete_flow(
        get_settings(), client, body.code, body.state, body.device_id, body.nonce, user.id
    )
    await identities.link_vk(session, user, vk_id, profile)
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


@router.delete("/consents/ai-transfer")
async def revoke_ai_transfer(user: CurrentUser, session: SessionDep) -> UserOut:
    await identities.revoke_ai_transfer(session, user)
    return await identities.user_out(session, user)
