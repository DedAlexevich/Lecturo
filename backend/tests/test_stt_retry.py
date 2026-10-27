import logging
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.providers.retry import RetryPolicy
from app.providers.yandex import RECOGNIZE_URL, YandexSpeechKitError, YandexSpeechToText
from tests.test_yandex_stt import saved_operation, yandex_settings

INTERNAL = {"code": 13, "message": "Internal"}


def make_audio(tmp_path: Path) -> Path:
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")
    return audio


def yandex_provider(start_replies: list, calls: dict) -> YandexSpeechToText:
    replies = iter(start_replies)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "storage.yandexcloud.net":
            calls.setdefault(request.method, []).append(request)
            return httpx.Response(200)
        if str(request.url) == RECOGNIZE_URL:
            calls.setdefault("start", []).append(request)
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply
        calls.setdefault("poll", []).append(request)
        return httpx.Response(200, json=saved_operation())

    return YandexSpeechToText(
        yandex_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )


def started(operation_id: str = "op1") -> httpx.Response:
    return httpx.Response(200, json={"id": operation_id, "done": False})


def test_policy_delays_grow_with_jitter():
    policy = RetryPolicy(attempts=5, base_seconds=2.0, factor=3.0, max_seconds=60.0)
    for attempt, expected in [(1, 2.0), (2, 6.0), (3, 18.0), (4, 54.0), (5, 60.0)]:
        assert expected * 0.8 <= policy.delay(attempt) <= expected * 1.2


def test_settings_defaults():
    settings = Settings()
    assert settings.stt_retry_attempts == 5
    assert settings.stt_retry_base_seconds == 2.0


async def test_yandex_start_recovers_after_internal_error(
    tmp_path: Path, retry_pauses: list[float], caplog: pytest.LogCaptureFixture
):
    calls: dict = {}
    provider = yandex_provider([httpx.Response(500, json=INTERNAL), started()], calls)
    with caplog.at_level(logging.WARNING, logger="app.providers.retry"):
        segments = await provider.transcribe(make_audio(tmp_path))

    assert len(segments) == 3
    assert len(calls["start"]) == 2
    assert len(retry_pauses) == 1
    assert len(calls["PUT"]) == 1
    assert "попытка 1 из 5" in caplog.text
    assert "api-key" not in caplog.text


@pytest.mark.parametrize("status", [429, 502, 503, 504])
async def test_yandex_start_retries_transient_statuses(
    tmp_path: Path, retry_pauses: list[float], status: int
):
    calls: dict = {}
    provider = yandex_provider([httpx.Response(status), started()], calls)
    await provider.transcribe(make_audio(tmp_path))
    assert len(calls["start"]) == 2


async def test_yandex_start_retries_code_13_with_other_status(
    tmp_path: Path, retry_pauses: list[float]
):
    calls: dict = {}
    provider = yandex_provider([httpx.Response(400, json=INTERNAL), started()], calls)
    await provider.transcribe(make_audio(tmp_path))
    assert len(calls["start"]) == 2


async def test_yandex_start_retries_network_errors(tmp_path: Path, retry_pauses: list[float]):
    request = httpx.Request("POST", RECOGNIZE_URL)
    calls: dict = {}
    provider = yandex_provider(
        [
            httpx.ReadTimeout("slow", request=request),
            httpx.RemoteProtocolError("closed", request=request),
            started(),
        ],
        calls,
    )
    await provider.transcribe(make_audio(tmp_path))
    assert len(calls["start"]) == 3
    assert len(retry_pauses) == 2


async def test_yandex_start_gives_up_after_all_attempts(tmp_path: Path, retry_pauses: list[float]):
    calls: dict = {}
    provider = yandex_provider([httpx.Response(500, json=INTERNAL)] * 5, calls)
    with pytest.raises(YandexSpeechKitError, match="запуск распознавания вернула 500"):
        await provider.transcribe(make_audio(tmp_path))

    assert len(calls["start"]) == 5
    assert len(retry_pauses) == 4
    assert retry_pauses[0] < retry_pauses[-1]
    assert len(calls["DELETE"]) == 1


async def test_yandex_network_failure_reports_readable_error(tmp_path: Path):
    request = httpx.Request("POST", RECOGNIZE_URL)
    calls: dict = {}
    provider = yandex_provider([httpx.ConnectTimeout("", request=request)] * 5, calls)
    with pytest.raises(YandexSpeechKitError, match="не удалась после 5 попыток"):
        await provider.transcribe(make_audio(tmp_path))


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_yandex_permanent_errors_are_not_retried(
    tmp_path: Path, retry_pauses: list[float], status: int
):
    calls: dict = {}
    provider = yandex_provider([httpx.Response(status, text="bad request")] * 5, calls)
    with pytest.raises(YandexSpeechKitError, match=str(status)):
        await provider.transcribe(make_audio(tmp_path))

    assert len(calls["start"]) == 1
    assert retry_pauses == []


async def test_yandex_upload_is_retried(tmp_path: Path, retry_pauses: list[float]):
    puts: list[httpx.Request] = []
    replies = iter([httpx.Response(503), httpx.Response(200)])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "storage.yandexcloud.net":
            if request.method == "PUT":
                puts.append(request)
                return next(replies)
            return httpx.Response(204)
        if str(request.url) == RECOGNIZE_URL:
            return started()
        return httpx.Response(200, json=saved_operation())

    provider = YandexSpeechToText(
        yandex_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    await provider.transcribe(make_audio(tmp_path))
    assert len(puts) == 2
    assert puts[1].content == b"OggS"
    assert len(retry_pauses) == 1


async def test_yandex_poll_retry_does_not_start_second_operation(
    tmp_path: Path, retry_pauses: list[float]
):
    starts = 0
    polls = iter([httpx.Response(500, json=INTERNAL), httpx.Response(200, json=saved_operation())])

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal starts
        if request.url.host == "storage.yandexcloud.net":
            return httpx.Response(200)
        if str(request.url) == RECOGNIZE_URL:
            starts += 1
            return started()
        return next(polls)

    provider = YandexSpeechToText(
        yandex_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    segments = await provider.transcribe(make_audio(tmp_path))
    assert len(segments) == 3
    assert starts == 1
    assert len(retry_pauses) == 1
