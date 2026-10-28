import enum
import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator, model_validator

from app.models import AuthProvider
from app.schemas.common import Schema


class RegisterIn(Schema):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)
    accept_terms: bool
    accept_personal_data: bool


class LoginIn(Schema):
    email: EmailStr
    password: str = Field(max_length=128)


class TokenOut(Schema):
    access_token: str
    token_type: str = "bearer"


class IdentityOut(Schema):
    provider: AuthProvider
    created_at: datetime


class TelegramNotifications(enum.StrEnum):
    not_linked = "not_linked"
    start_required = "start_required"
    ready = "ready"
    blocked = "blocked"


class UserOut(Schema):
    id: uuid.UUID
    email: str | None
    email_verified: bool
    display_name: str
    ai_transfer_accepted_at: datetime | None
    identities: list[IdentityOut]
    telegram_notifications: TelegramNotifications
    is_admin: bool


class TelegramLoginIn(Schema):
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class TelegramLinkIn(Schema):
    id: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int | None = None
    hash: str | None = None
    telegram_init_data: str | None = None

    @model_validator(mode="after")
    def require_one_source(self) -> "TelegramLinkIn":
        widget = (self.id, self.first_name, self.auth_date, self.hash)
        if self.telegram_init_data is not None:
            if any(value is not None for value in widget):
                raise ValueError("Укажите либо telegram_init_data, либо данные виджета")
        elif any(value is None for value in widget):
            raise ValueError("Нужны telegram_init_data или данные виджета Telegram")
        return self


class TelegramSignupIn(TelegramLoginIn):
    accept_terms: bool = False
    accept_personal_data: bool = False


class TelegramWebAppIn(Schema):
    init_data: str
    accept_terms: bool = False
    accept_personal_data: bool = False


class ProvidersOut(Schema):
    vk: bool
    yandex: bool


class VkStartIn(Schema):
    accept_terms: bool = False
    accept_personal_data: bool = False


class VkStartOut(Schema):
    url: str
    nonce: str


class VkCallbackIn(Schema):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=256)
    device_id: str = Field(min_length=1, max_length=256)
    nonce: str = Field(min_length=1, max_length=256)


class YandexStartIn(Schema):
    accept_terms: bool = False
    accept_personal_data: bool = False


class YandexStartOut(Schema):
    url: str
    nonce: str


class YandexCallbackIn(Schema):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=256)
    nonce: str = Field(min_length=1, max_length=256)


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
    password: str | None = Field(default=None, max_length=128)
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
