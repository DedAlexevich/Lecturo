import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.models import AuthProvider
from app.schemas.common import Schema


class RegisterIn(Schema):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)
    accept_terms: bool


class LoginIn(Schema):
    email: EmailStr
    password: str


class TokenOut(Schema):
    access_token: str
    token_type: str = "bearer"


class IdentityOut(Schema):
    provider: AuthProvider
    created_at: datetime


class UserOut(Schema):
    id: uuid.UUID
    email: str | None
    email_verified: bool
    display_name: str
    ai_transfer_accepted_at: datetime | None
    identities: list[IdentityOut]


class TelegramLoginIn(Schema):
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class TelegramWebAppIn(Schema):
    init_data: str


class EmailIn(Schema):
    email: EmailStr


class TokenIn(Schema):
    token: str


class PasswordResetIn(Schema):
    token: str
    password: str = Field(min_length=8, max_length=128)


class EmailIdentityIn(Schema):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AccountDeleteIn(Schema):
    password: str | None = None
    telegram: TelegramLoginIn | None = None
    telegram_init_data: str | None = None


class ProfileUpdateIn(Schema):
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Имя не может быть пустым")
        return value


class PasswordChangeIn(Schema):
    current_password: str | None = None
    new_password: str = Field(min_length=8, max_length=128)
