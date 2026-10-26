from datetime import UTC, datetime

from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError

from app.models import User
from app.services.legal import read_document

CONSENT_REQUIRED = (
    "Для создания аккаунта нужно принять пользовательское соглашение "
    "и согласие на обработку персональных данных"
)


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


def require_telegram_signup_consents(accept_terms: bool, accept_personal_data: bool) -> None:
    if not (accept_terms and accept_personal_data):
        raise HTTPException(status.HTTP_403_FORBIDDEN, CONSENT_REQUIRED)


def record_signup_consents(user: User) -> None:
    now = datetime.now(UTC)
    user.terms_accepted_at = now
    user.terms_revision = read_document("terms").revision_date
    user.personal_data_accepted_at = now
    user.personal_data_revision = read_document("personal-data-consent").revision_date
