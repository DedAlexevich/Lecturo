import hashlib
import hmac
import math
import time
import uuid
from urllib.parse import urlencode

from app.core.config import get_settings

VIDEO_LINK_TTL_SEC = 6 * 3600
VIDEO_LINK_STEP_SEC = 3600


def video_signature(lecture_id: uuid.UUID, expires: int, share_token: str | None) -> str:
    message = f"video:{lecture_id}:{expires}:{share_token or ''}"
    key = get_settings().secret_key.encode()
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


def signed_video_url(lecture_id: uuid.UUID, share_token: str | None = None) -> str:
    expires = (
        math.ceil((time.time() + VIDEO_LINK_TTL_SEC) / VIDEO_LINK_STEP_SEC) * VIDEO_LINK_STEP_SEC
    )
    params: dict[str, str | int] = {
        "expires": expires,
        "signature": video_signature(lecture_id, expires, share_token),
    }
    if share_token is not None:
        params["share"] = share_token
    return f"/media/{lecture_id}.mp4?{urlencode(params)}"


def is_valid_signature(
    lecture_id: uuid.UUID, expires: int, signature: str, share_token: str | None
) -> bool:
    if expires < time.time():
        return False
    expected = video_signature(lecture_id, expires, share_token)
    return hmac.compare_digest(expected, signature)
