from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthIdentity, AuthProvider, User
from app.services.consents import record_signup_consents

hasher = PasswordHasher()
missing_user_hash = hasher.hash("missing-user")


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def register_user(
    session: AsyncSession, email: str, password: str, display_name: str
) -> User:
    email = normalize_email(email)
    user = User(email=email, password_hash=hash_password(password), display_name=display_name)
    user.identities.append(AuthIdentity(provider=AuthProvider.email, provider_user_id=email))
    record_signup_consents(user)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Пользователь с таким email уже есть"
        ) from None
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    has_password = user is not None and bool(user.password_hash)
    password_hash = user.password_hash if has_password else missing_user_hash
    if not verify_password(password_hash, password) or not has_password:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    return user
