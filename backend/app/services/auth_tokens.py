import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthToken, AuthTokenKind, User

TOKEN_TTL = {
    AuthTokenKind.verify_email: timedelta(hours=24),
    AuthTokenKind.reset_password: timedelta(hours=1),
}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_token(session: AsyncSession, user_id: uuid.UUID, kind: AuthTokenKind) -> str:
    token = secrets.token_urlsafe(32)
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())
    await session.execute(
        delete(AuthToken).where(
            AuthToken.user_id == user_id,
            AuthToken.kind == kind,
            AuthToken.used_at.is_(None),
        )
    )
    session.add(
        AuthToken(
            user_id=user_id,
            kind=kind,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + TOKEN_TTL[kind],
        )
    )
    await session.commit()
    return token


async def consume_token(session: AsyncSession, token: str, kind: AuthTokenKind) -> uuid.UUID:
    now = datetime.now(UTC)
    user_id = await session.scalar(
        update(AuthToken)
        .where(
            AuthToken.token_hash == hash_token(token),
            AuthToken.kind == kind,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(AuthToken.user_id)
    )
    if user_id is None:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ссылка недействительна или устарела")
    return user_id
