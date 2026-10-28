from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import decode_access_token
from app.models import User
from app.services.quota import has_subscription

bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def user_by_token(session: AsyncSession, token: str) -> User | None:
    grant = decode_access_token(token)
    if grant is None:
        return None
    user = await session.get(User, grant.user_id)
    if user is None or user.token_version != grant.version or user.blocked_at is not None:
        return None
    return user


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    user = await user_by_token(session, credentials.credentials) if credentials else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужно войти")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_admin_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    user = await user_by_token(session, credentials.credentials) if credentials else None
    if user is None or not user.is_admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return user


AdminUser = Annotated[User, Depends(get_admin_user)]


async def require_subscription(session: SessionDep, user: CurrentUser) -> User:
    if not await has_subscription(session, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "subscription_required", "message": "Доступно только с подпиской"},
        )
    return user


RequireSubscription = Annotated[User, Depends(require_subscription)]
