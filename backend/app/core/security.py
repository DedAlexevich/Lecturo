import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"
EXPORT_SCOPE = "export"
EXPORT_TOKEN_TTL = timedelta(minutes=2)

ExportFormat = Literal["pdf", "srt", "vtt"]


@dataclass(frozen=True)
class ExportGrant:
    user_id: uuid.UUID
    lecture_id: uuid.UUID
    export_format: str


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {"sub": str(user_id), "exp": expires}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
        if "scope" in payload:
            return None
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def create_export_token(
    user_id: uuid.UUID, lecture_id: uuid.UUID, export_format: ExportFormat
) -> tuple[str, datetime]:
    expires = datetime.now(UTC) + EXPORT_TOKEN_TTL
    payload = {
        "sub": str(user_id),
        "aud": EXPORT_SCOPE,
        "scope": EXPORT_SCOPE,
        "lecture_id": str(lecture_id),
        "format": export_format,
        "exp": expires,
    }
    return jwt.encode(payload, get_settings().secret_key, algorithm=ALGORITHM), expires


def decode_export_token(token: str) -> ExportGrant | None:
    try:
        payload = jwt.decode(
            token,
            get_settings().secret_key,
            algorithms=[ALGORITHM],
            audience=EXPORT_SCOPE,
            options={"require": ["exp", "aud", "sub"]},
        )
        if payload.get("scope") != EXPORT_SCOPE:
            return None
        return ExportGrant(
            user_id=uuid.UUID(payload["sub"]),
            lecture_id=uuid.UUID(payload["lecture_id"]),
            export_format=str(payload["format"]),
        )
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None
