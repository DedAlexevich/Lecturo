from fastapi import APIRouter, status

from app.core.deps import CurrentUser, SessionDep
from app.core.errors import not_ready
from app.models import AuthProvider
from app.schemas.user import (
    AccountDeleteIn,
    EmailIdentityIn,
    IdentityOut,
    TelegramLoginIn,
    UserOut,
)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
async def get_me(user: CurrentUser, session: SessionDep) -> UserOut:
    await session.refresh(user, ["identities"])
    return UserOut(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        display_name=user.display_name,
        ai_transfer_accepted_at=user.ai_transfer_accepted_at,
        identities=[IdentityOut.model_validate(identity) for identity in user.identities],
    )


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(body: AccountDeleteIn, user: CurrentUser) -> None:
    not_ready()


@router.post("/identities/telegram")
async def link_telegram(body: TelegramLoginIn, user: CurrentUser) -> UserOut:
    not_ready()


@router.post("/identities/email")
async def link_email(body: EmailIdentityIn, user: CurrentUser) -> UserOut:
    not_ready()


@router.delete("/identities/{provider}")
async def unlink_identity(provider: AuthProvider, user: CurrentUser) -> UserOut:
    not_ready()


@router.post("/consents/ai-transfer")
async def accept_ai_transfer(user: CurrentUser) -> UserOut:
    not_ready()
