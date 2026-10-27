import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk


class NoticeChannel(enum.StrEnum):
    email = "email"
    telegram = "telegram"


class LegalRevision(Base):
    __tablename__ = "legal_revisions"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision_date: Mapped[date] = mapped_column(Date, primary_key=True)
    effective_date: Mapped[date] = mapped_column(Date)
    announced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LegalNotice(UUIDPk, CreatedAt, Base):
    __tablename__ = "legal_notices"
    __table_args__ = (UniqueConstraint("user_id", "slug", "revision_date", "channel"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(64))
    revision_date: Mapped[date] = mapped_column(Date)
    channel: Mapped[NoticeChannel] = mapped_column(Enum(NoticeChannel, name="notice_channel"))
    subject: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(String(512))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
