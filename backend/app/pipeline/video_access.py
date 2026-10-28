import hashlib
import hmac
import math
import time
import uuid
from typing import Literal
from urllib.parse import urlencode

from app.core.config import get_settings
from app.models import Lecture, LectureStatus
from app.pipeline.download import is_yandex_disk

VIDEO_LINK_TTL_SEC = 6 * 3600
VIDEO_LINK_STEP_SEC = 3600

MediaKind = Literal["video", "audio", "stream"]


def media_signature(
    kind: MediaKind, lecture_id: uuid.UUID, expires: int, share_token: str | None
) -> str:
    message = f"{kind}:{lecture_id}:{expires}:{share_token or ''}"
    key = get_settings().secret_key.encode()
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


def signed_query(kind: MediaKind, lecture_id: uuid.UUID, share_token: str | None) -> str:
    expires = (
        math.ceil((time.time() + VIDEO_LINK_TTL_SEC) / VIDEO_LINK_STEP_SEC) * VIDEO_LINK_STEP_SEC
    )
    params: dict[str, str | int] = {
        "expires": expires,
        "signature": media_signature(kind, lecture_id, expires, share_token),
    }
    if share_token is not None:
        params["share"] = share_token
    return urlencode(params)


def signed_video_url(lecture_id: uuid.UUID, share_token: str | None = None) -> str:
    return f"/media/{lecture_id}.mp4?{signed_query('video', lecture_id, share_token)}"


def signed_stream_url(lecture_id: uuid.UUID, share_token: str | None = None) -> str:
    return f"/api/v1/lectures/{lecture_id}/stream?{signed_query('stream', lecture_id, share_token)}"


def playable_video_url(lecture: Lecture, share_token: str | None = None) -> str | None:
    if lecture.video_path:
        return signed_video_url(lecture.id, share_token)
    if (
        lecture.status != LectureStatus.failed
        and lecture.source_url
        and is_yandex_disk(lecture.source_url)
    ):
        return signed_stream_url(lecture.id, share_token)
    return None


def signed_audio_url(lecture_id: uuid.UUID) -> str:
    return f"/api/v1/lectures/{lecture_id}/audio?{signed_query('audio', lecture_id, None)}"


def is_valid_signature(
    lecture_id: uuid.UUID,
    expires: int,
    signature: str,
    share_token: str | None,
    kind: MediaKind = "video",
) -> bool:
    if expires < time.time():
        return False
    expected = media_signature(kind, lecture_id, expires, share_token)
    return hmac.compare_digest(expected, signature)
