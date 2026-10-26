import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPk


class AuthProvider(enum.StrEnum):
    email = "email"
    telegram = "telegram"
    vk = "vk"
    yandex = "yandex"


class AuthTokenKind(enum.StrEnum):
    verify_email = "verify_email"
    reset_password = "reset_password"


class User(UUIDPk, CreatedAt, Base):
    __tablename__ = "users"

    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    ai_transfer_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_revision: Mapped[date | None] = mapped_column(Date)
    personal_data_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    personal_data_revision: Mapped[date | None] = mapped_column(Date)
    quota_week_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    identities: Mapped[list["AuthIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthIdentity(UUIDPk, CreatedAt, Base):
    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[AuthProvider] = mapped_column(Enum(AuthProvider, name="auth_provider"))
    provider_user_id: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)

    user: Mapped[User] = relationship(back_populates="identities")


class AuthToken(UUIDPk, CreatedAt, Base):
    __tablename__ = "auth_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[AuthTokenKind] = mapped_column(Enum(AuthTokenKind, name="auth_token_kind"))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
