import uuid
from datetime import datetime

from pydantic import EmailStr, Field

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
    identities: list[IdentityOut]
