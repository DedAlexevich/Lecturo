import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk


class PaymentKind(enum.StrEnum):
    subscription = "subscription"
    package = "package"


class PaymentStatus(enum.StrEnum):
    pending = "pending"
    succeeded = "succeeded"
    canceled = "canceled"


class UsageSource(enum.StrEnum):
    weekly = "weekly"
    package = "package"
    local_embeddings = "local_embeddings"


class Payment(UUIDPk, CreatedAt, Base):
    __tablename__ = "payments"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[PaymentKind] = mapped_column(Enum(PaymentKind, name="payment_kind"))
    product_code: Mapped[str] = mapped_column(String(64))
    amount_kopecks: Mapped[int] = mapped_column(Integer)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), default=PaymentStatus.pending
    )
    idempotence_key: Mapped[str] = mapped_column(String(64), unique=True)
    yookassa_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)


class Subscription(UUIDPk, CreatedAt, Base):
    __tablename__ = "subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HourPackage(UUIDPk, CreatedAt, Base):
    __tablename__ = "hour_packages"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    seconds_total: Mapped[int] = mapped_column(Integer)
    seconds_left: Mapped[int] = mapped_column(Integer)


class UsageEntry(UUIDPk, CreatedAt, Base):
    __tablename__ = "usage_entries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    lecture_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lectures.id", ondelete="SET NULL")
    )
    source: Mapped[UsageSource] = mapped_column(Enum(UsageSource, name="usage_source"))
    package_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hour_packages.id"))
    seconds: Mapped[int] = mapped_column(Integer)
