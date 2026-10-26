from fastapi import HTTPException, status

from app.models import User

AI_TRANSFER_REQUIRED = "Нет согласия на передачу данных на серверную обработку"


def require_ai_transfer_consent(user: User) -> None:
    if user.ai_transfer_accepted_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, AI_TRANSFER_REQUIRED)
