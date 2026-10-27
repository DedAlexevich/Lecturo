import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
INTERNAL_ERROR_CODE = 13
JITTER_RATIO = 0.2


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 5
    base_seconds: float = 2.0
    factor: float = 3.0
    max_seconds: float = 60.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "RetryPolicy":
        return cls(
            attempts=max(1, settings.stt_retry_attempts),
            base_seconds=settings.stt_retry_base_seconds,
            factor=settings.stt_retry_factor,
            max_seconds=settings.stt_retry_max_seconds,
        )

    def delay(self, failed_attempt: int) -> float:
        delay = min(self.base_seconds * self.factor ** (failed_attempt - 1), self.max_seconds)
        return delay * random.uniform(1 - JITTER_RATIO, 1 + JITTER_RATIO)


async def sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def is_retryable_response(response: httpx.Response) -> bool:
    if response.status_code in RETRYABLE_STATUSES:
        return True
    if not response.is_error:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("code") == INTERNAL_ERROR_CODE


async def request_with_retry(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    policy: RetryPolicy,
    provider: str,
    action: str,
    error_cls: type[Exception],
) -> httpx.Response:
    attempt = 0
    while True:
        attempt += 1
        failure: httpx.TransportError | None = None
        response: httpx.Response | None = None
        try:
            response = await send()
        except httpx.TransportError as error:
            failure = error
            reason = type(error).__name__
        else:
            if not is_retryable_response(response):
                return response
            reason = f"ответ {response.status_code}"
        if attempt >= policy.attempts:
            if response is not None:
                return response
            raise error_cls(
                f"{provider}: {action} не удалась после {attempt} попыток ({reason})"
            ) from failure
        delay = policy.delay(attempt)
        logger.warning(
            "%s: %s, временная ошибка (%s), попытка %d из %d, повтор через %.1f с",
            provider,
            action,
            reason,
            attempt,
            policy.attempts,
            delay,
        )
        await sleep(delay)
