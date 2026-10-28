import uuid
from datetime import datetime

from pydantic import AwareDatetime, Field, model_validator

from app.models import PaymentStatus, PromoKind
from app.schemas.common import Schema

CODE_PATTERN = r"^[A-Za-z0-9_-]{4,32}$"


class PromoIn(Schema):
    code: str = Field(min_length=1, max_length=64)


class PromoOut(Schema):
    code: str
    kind: PromoKind
    hours: int | None
    days: int | None
    discount_percent: int | None
    discount_kopecks: int | None
    applied: bool
    message: str


class PromoCreateIn(Schema):
    code: str | None = Field(default=None, pattern=CODE_PATTERN)
    kind: PromoKind
    hours: int | None = Field(default=None, ge=1, le=1000)
    days: int | None = Field(default=None, ge=1, le=366)
    discount_percent: int | None = Field(default=None, ge=1, le=99)
    discount_kopecks: int | None = Field(default=None, ge=100, le=10_000_000)
    max_redemptions: int | None = Field(default=None, ge=1, le=1_000_000)
    valid_until: AwareDatetime | None = None
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def check_value(self) -> "PromoCreateIn":
        values = {
            "hours": self.hours,
            "days": self.days,
            "discount_percent": self.discount_percent,
            "discount_kopecks": self.discount_kopecks,
        }
        given = {name for name, value in values.items() if value is not None}
        allowed = {
            PromoKind.hours: [{"hours"}],
            PromoKind.subscription_days: [{"days"}],
            PromoKind.discount: [{"discount_percent"}, {"discount_kopecks"}],
        }[self.kind]
        if given not in allowed:
            raise ValueError("Укажите одно значение, подходящее к типу промокода")
        return self


class PromoCodeOut(Schema):
    id: uuid.UUID
    created_at: datetime
    code: str
    kind: PromoKind
    hours: int | None
    days: int | None
    discount_percent: int | None
    discount_kopecks: int | None
    max_redemptions: int | None
    valid_until: datetime | None
    disabled_at: datetime | None
    note: str
    redeemed: int


class PromoRedemptionOut(Schema):
    created_at: datetime
    user_id: uuid.UUID
    user_label: str
    payment_status: PaymentStatus | None
    payment_amount_kopecks: int | None
    discount_kopecks: int | None
