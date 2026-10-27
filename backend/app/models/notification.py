import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk


class NotificationKind(enum.StrEnum):
    lecture = "lecture"
    regenerate = "regenerate"
    quiz = "quiz"


class NotificationOutcome(enum.StrEnum):
    ready = "ready"
    failed = "failed"


class NotificationEvent(UUIDPk, CreatedAt, Base):
    __tablename__ = "notification_events"
    __table_args__ = (
        Index(
            "ix_notification_events_pending",
            "next_attempt_at",
            postgresql_where=text("sent_at IS NULL AND expired_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    lecture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lectures.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[NotificationKind] = mapped_column(Enum(NotificationKind, name="notification_kind"))
    outcome: Mapped[NotificationOutcome] = mapped_column(
        Enum(NotificationOutcome, name="notification_outcome")
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
