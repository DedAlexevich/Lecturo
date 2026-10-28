import enum
import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk


class AdminAction(enum.StrEnum):
    admin_granted = "admin_granted"
    admin_revoked = "admin_revoked"


class AdminAuditEntry(UUIDPk, CreatedAt, Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        Index("ix_admin_audit_log_created_at", "created_at"),
        Index("ix_admin_audit_log_action_created_at", "action", "created_at"),
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_label: Mapped[str] = mapped_column(String(320), default="")
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    target_label: Mapped[str] = mapped_column(String(320), default="")
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
