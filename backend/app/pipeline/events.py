import json
import logging
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.models import LectureStatus

CHANNEL = "lecture-events"

logger = logging.getLogger(__name__)


async def publish_status(
    lecture_id: uuid.UUID, user_id: uuid.UUID, status: LectureStatus, error: str | None = None
) -> None:
    message = json.dumps(
        {
            "lecture_id": str(lecture_id),
            "user_id": str(user_id),
            "status": status.value,
            "error": error,
        },
        ensure_ascii=False,
    )
    redis = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        await redis.publish(CHANNEL, message)
    except (OSError, RedisError):
        logger.warning("Не удалось опубликовать статус лекции %s", lecture_id, exc_info=True)
    finally:
        await redis.aclose()
