import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPk


class PromoKind(enum.StrEnum):
    hours = "hours"
    subscription_days = "subscription_days"
    discount = "discount"


class PromoCode(UUIDPk, CreatedAt, Base):
    __tablename__ = "promo_codes"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    kind: Mapped[PromoKind] = mapped_column(String(32))
    hours: Mapped[int | None] = mapped_column(Integer)
    days: Mapped[int | None] = mapped_column(Integer)
    discount_percent: Mapped[int | None] = mapped_column(Integer)
    discount_kopecks: Mapped[int | None] = mapped_column(Integer)
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class PromoRedemption(UUIDPk, CreatedAt, Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (Index("ix_promo_redemptions_promo_id_user_id", "promo_id", "user_id"),)

    promo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("promo_codes.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), index=True
    )
