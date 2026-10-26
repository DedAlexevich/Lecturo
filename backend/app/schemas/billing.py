import uuid
from datetime import datetime

from app.models import PaymentKind, PaymentStatus
from app.schemas.common import Schema


class QuotaOut(Schema):
    weekly_limit_sec: int
    weekly_used_sec: int
    package_left_sec: int
    resets_at: datetime
    subscription_until: datetime | None


class ProductOut(Schema):
    code: str
    kind: PaymentKind
    title: str
    price_rub: int
    seconds: int | None


class PaymentIn(Schema):
    product_code: str
    return_url: str | None = None


class PaymentOut(Schema):
    id: uuid.UUID
    kind: PaymentKind
    product_code: str
    amount_kopecks: int
    status: PaymentStatus
    confirmation_url: str | None = None
    created_at: datetime
    paid_at: datetime | None


class QueuePlanIn(Schema):
    lecture_ids: list[uuid.UUID]
