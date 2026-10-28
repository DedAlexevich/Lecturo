import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk


class AlertKind(enum.StrEnum):
    service_down = "service_down"
    queue_stalled = "queue_stalled"
    disk_low = "disk_low"
    memory_low = "memory_low"
    payment = "payment"
    webhook_error = "webhook_error"


class AlertState(enum.StrEnum):
    firing = "firing"
    resolved = "resolved"
    event = "event"


class AlertSignal(UUIDPk, CreatedAt, Base):
    __tablename__ = "admin_alert_signals"
    __table_args__ = (
        CheckConstraint("state IN ('firing', 'resolved', 'event')", name="state"),
        Index(
            "ix_admin_alert_signals_pending",
            "created_at",
            postgresql_where=text("dispatched_at IS NULL"),
        ),
        Index("ix_admin_alert_signals_kind_dispatched_at", "kind", "dispatched_at"),
    )

    kind: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertSettings(Base):
    __tablename__ = "admin_alert_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    muted_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), default=list, server_default=text("'{}'")
    )
    recoveries: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AlertDelivery(UUIDPk, CreatedAt, Base):
    __tablename__ = "admin_alert_deliveries"
    __table_args__ = (
        Index(
            "ix_admin_alert_deliveries_pending",
            "next_attempt_at",
            postgresql_where=text("sent_at IS NULL AND expired_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
