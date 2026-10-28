import uuid
from datetime import date, datetime

from pydantic import Field

from app.models import AuthProvider, LectureStatus, PaymentKind, PaymentStatus, SourceType
from app.schemas.billing import QuotaOut
from app.schemas.common import Schema


class UserBriefOut(Schema):
    id: uuid.UUID
    email: str | None
    display_name: str
    created_at: datetime
    is_admin: bool
    blocked: bool
    telegram_username: str | None
    subscription_until: datetime | None
    package_left_sec: int


class UserIdentityOut(Schema):
    provider: AuthProvider
    created_at: datetime


class UserConsentsOut(Schema):
    terms_accepted_at: datetime | None
    terms_revision: date | None
    personal_data_accepted_at: datetime | None
    personal_data_revision: date | None
    ai_transfer_accepted_at: datetime | None
    ai_transfer_revision: date | None


class UserPaymentOut(Schema):
    id: uuid.UUID
    kind: PaymentKind
    product_code: str
    amount_kopecks: int
    status: PaymentStatus
    created_at: datetime
    paid_at: datetime | None


class UserLectureOut(Schema):
    id: uuid.UUID
    status: LectureStatus
    source_type: SourceType
    duration_sec: float | None
    created_at: datetime


class UserLecturesOut(Schema):
    total: int
    by_status: dict[LectureStatus, int]
    recent: list[UserLectureOut]


class UserCardOut(Schema):
    id: uuid.UUID
    email: str | None
    email_verified: bool
    display_name: str
    created_at: datetime
    is_admin: bool
    blocked_at: datetime | None
    blocked_reason: str | None
    identities: list[UserIdentityOut]
    consents: UserConsentsOut
    quota: QuotaOut
    payments: list[UserPaymentOut]
    lectures: UserLecturesOut


class AdminReasonIn(Schema):
    reason: str = Field(min_length=3, max_length=500)


class GrantHoursIn(AdminReasonIn):
    hours: int = Field(ge=1, le=1000)


class ExtendSubscriptionIn(AdminReasonIn):
    days: int = Field(ge=1, le=366)


class StatsDayOut(Schema):
    day: date
    new_users: int
    lectures: int
    processed_seconds: int
    failed_lectures: int
    payments: int
    revenue_kopecks: int


class StatsTotalsOut(Schema):
    new_users: int
    lectures: int
    processed_seconds: int
    failed_lectures: int
    payments: int
    revenue_kopecks: int
    refunds: int
    refunded_kopecks: int


class StatsOut(Schema):
    date_from: date
    date_to: date
    generated_at: datetime
    totals: StatsTotalsOut
    days: list[StatsDayOut]
