import enum
import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk


class AdminAction(enum.StrEnum):
    admin_granted = "admin_granted"
    admin_revoked = "admin_revoked"
    logs_stream_started = "logs_stream_started"
    lecture_retried = "lecture_retried"
    backup_downloaded = "backup_downloaded"
    backup_created = "backup_created"
    backup_create_failed = "backup_create_failed"
    backup_uploaded = "backup_uploaded"
    backup_deleted = "backup_deleted"
    backup_upload_rejected = "backup_upload_rejected"
    restore_started = "restore_started"
    restore_finished = "restore_finished"
    restore_failed = "restore_failed"
    restore_denied = "restore_denied"
    maintenance_disabled = "maintenance_disabled"
    users_searched = "users_searched"
    user_viewed = "user_viewed"
    hours_granted = "hours_granted"
    subscription_extended = "subscription_extended"
    user_blocked = "user_blocked"
    user_unblocked = "user_unblocked"
    alert_settings_changed = "alert_settings_changed"
    promo_created = "promo_created"
    promo_disabled = "promo_disabled"


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


class BusinessEventKind(enum.StrEnum):
    payment_created = "payment_created"
    payment_succeeded = "payment_succeeded"
    payment_canceled = "payment_canceled"
    payment_refunded = "payment_refunded"
    subscription_granted = "subscription_granted"
    webhook_received = "webhook_received"
    webhook_rejected = "webhook_rejected"
    register = "register"
    login = "login"
    login_failed = "login_failed"
    account_deleted = "account_deleted"


class BusinessEvent(UUIDPk, CreatedAt, Base):
    __tablename__ = "business_events"
    __table_args__ = (
        Index("ix_business_events_created_at", "created_at"),
        Index("ix_business_events_kind_created_at", "kind", "created_at"),
    )

    kind: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    user_label: Mapped[str] = mapped_column(String(320), default="")
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
