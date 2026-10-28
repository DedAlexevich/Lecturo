from datetime import UTC, date, datetime
from functools import cache

from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LegalRevision, User
from app.services.legal import read_document

CONSENT_REQUIRED = (
    "Для создания аккаунта нужно принять пользовательское соглашение "
    "и согласие на обработку персональных данных"
)

AI_TRANSFER_REQUIRED = (
    "Нет согласия на передачу данных провайдерам ИИ: оно не давалось или отозвано. "
    "Дайте согласие и повторите обработку"
)

ACCEPTANCES = {
    "terms": (User.terms_accepted_at, User.terms_revision),
    "personal-data-consent": (User.personal_data_accepted_at, User.personal_data_revision),
    "ai-transfer": (User.ai_transfer_accepted_at, User.ai_transfer_revision),
}


def require_signup_consents(accept_terms: bool, accept_personal_data: bool) -> None:
    missing = []
    if not accept_terms:
        missing.append(("accept_terms", "Нужно принять пользовательское соглашение"))
    if not accept_personal_data:
        missing.append(
            ("accept_personal_data", "Нужно дать согласие на обработку персональных данных")
        )
    if missing:
        raise RequestValidationError(
            [
                {"loc": ("body", field), "msg": message, "type": "value_error"}
                for field, message in missing
            ]
        )


def require_provider_signup_consents(accept_terms: bool, accept_personal_data: bool) -> None:
    if not (accept_terms and accept_personal_data):
        raise HTTPException(status.HTTP_403_FORBIDDEN, CONSENT_REQUIRED)


@cache
def current_ai_transfer_revision() -> date:
    return read_document("ai-transfer").revision_date


def ai_transfer_given(accepted_at: datetime | None, revision: date | None) -> bool:
    return accepted_at is not None and revision is not None


async def apply_effective_revisions(session: AsyncSession, today: date) -> None:
    announced = await session.execute(
        select(LegalRevision.slug, LegalRevision.revision_date)
        .where(LegalRevision.effective_date <= today, LegalRevision.slug.in_(ACCEPTANCES))
        .order_by(LegalRevision.revision_date)
    )
    for slug, revision_date in announced.all():
        accepted_at, revision = ACCEPTANCES[slug]
        await session.execute(
            update(User)
            .where(accepted_at.is_not(None), revision.is_not(None), revision < revision_date)
            .values({revision: revision_date})
            .execution_options(synchronize_session=False)
        )


def require_ai_transfer_consent(user: User) -> None:
    if not ai_transfer_given(user.ai_transfer_accepted_at, user.ai_transfer_revision):
        raise HTTPException(status.HTTP_403_FORBIDDEN, AI_TRANSFER_REQUIRED)


def record_signup_consents(user: User) -> None:
    now = datetime.now(UTC)
    user.terms_accepted_at = now
    user.terms_revision = read_document("terms").revision_date
    user.personal_data_accepted_at = now
    user.personal_data_revision = read_document("personal-data-consent").revision_date
