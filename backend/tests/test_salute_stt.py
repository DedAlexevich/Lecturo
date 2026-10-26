import json
import time
from collections.abc import Iterable
from pathlib import Path

import certifi
import httpx
import pytest

from app.core.config import Settings
from app.providers import Segment, get_speech_to_text
from app.providers.salute import (
    API_URL,
    OAUTH_URL,
    SaluteSpeechError,
    SaluteSpeechToText,
    parse_recognition,
)

FIXTURE = Path(__file__).parent / "fixtures" / "salute_stt_result.json"


def salute_settings() -> Settings:
    return Settings(stt_provider="salute", salute_auth_key="auth-key")


def saved_result() -> list:
    return json.loads(FIXTURE.read_text())


def token_response(token: str = "token-1", ttl: float = 1800) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": token, "expires_at": int((time.time() + ttl) * 1000)}
    )


def result(payload: dict) -> httpx.Response:
    return httpx.Response(200, json={"status": 200, "result": payload})


def api_handler(requests: list[httpx.Request], tasks: Iterable[dict]):
    polls = iter(tasks)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url) == OAUTH_URL:
            return token_response()
        match request.url.path:
            case "/rest/v1/data:upload":
                return result({"request_file_id": "file-1"})
            case "/rest/v1/speech:async_recognize":
                return result({"id": "task-1", "status": "NEW"})
            case "/rest/v1/task:get":
                return result(next(polls))
            case "/rest/v1/data:download":
                return httpx.Response(200, json=saved_result())
        return httpx.Response(404)

    return handler


def test_parse_recognition_from_saved_response():
    segments = parse_recognition(saved_result())

    assert segments == [
        Segment(start=0.88, end=2.4, text="Сегодня разберём производные."),
        Segment(start=3.16, end=4.66, text="Начнём с определения."),
        Segment(start=65.3, end=66.42, text="пример первый"),
    ]
    assert all(s.start <= s.end for s in segments)
    assert all(a.end <= b.start for a, b in zip(segments, segments[1:], strict=False))


def test_parse_recognition_empty_response():
    assert parse_recognition([]) == []


def test_factory_returns_salute_provider():
    assert isinstance(get_speech_to_text(salute_settings()), SaluteSpeechToText)


def test_factory_requires_auth_key():
    with pytest.raises(ValueError, match="SALUTE_AUTH_KEY"):
        get_speech_to_text(Settings(stt_provider="salute"))


async def test_transcribe_uploads_polls_and_downloads(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS-audio")
    requests: list[httpx.Request] = []
    handler = api_handler(
        requests,
        [
            {"id": "task-1", "status": "RUNNING"},
            {"id": "task-1", "status": "DONE", "response_file_id": "result-1"},
        ],
    )

    provider = SaluteSpeechToText(
        salute_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    segments = await provider.transcribe(audio, "ru")

    assert segments[0].text == "Сегодня разберём производные."
    oauth, upload, start, poll1, poll2, download = requests
    assert oauth.headers["authorization"] == "Basic auth-key"
    assert oauth.headers["rquid"]
    assert oauth.content == b"scope=SALUTE_SPEECH_PERS"
    assert upload.url == f"{API_URL}/data:upload"
    assert upload.headers["authorization"] == "Bearer token-1"
    assert upload.headers["content-type"] == "audio/ogg;codecs=opus"
    assert upload.content == b"OggS-audio"
    body = json.loads(start.content)
    assert body["request_file_id"] == "file-1"
    assert body["options"]["audio_encoding"] == "OPUS"
    assert body["options"]["language"] == "ru-RU"
    assert poll1.url.params["id"] == "task-1"
    assert poll2.url.params["id"] == "task-1"
    assert download.url.params["response_file_id"] == "result-1"


async def test_transcribe_sends_mp3_encoding(tmp_path: Path):
    audio = tmp_path / "lecture.mp3"
    audio.write_bytes(b"ID3")
    requests: list[httpx.Request] = []
    handler = api_handler(
        requests, [{"id": "task-1", "status": "DONE", "response_file_id": "result-1"}]
    )

    provider = SaluteSpeechToText(
        salute_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    await provider.transcribe(audio, "en")

    upload, start = requests[1], requests[2]
    assert upload.headers["content-type"] == "audio/mpeg"
    body = json.loads(start.content)
    assert body["options"]["audio_encoding"] == "MP3"
    assert body["options"]["language"] == "en-US"


async def test_token_is_reused_until_expiry(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")
    requests: list[httpx.Request] = []
    handler = api_handler(
        requests,
        [{"id": "task-1", "status": "DONE", "response_file_id": "result-1"}] * 2,
    )

    provider = SaluteSpeechToText(
        salute_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    await provider.transcribe(audio)
    await provider.transcribe(audio)

    assert [str(r.url) for r in requests].count(OAUTH_URL) == 1


async def test_token_is_refreshed_after_unauthorized(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")
    tokens = iter(["old", "new"])
    uploads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_URL:
            return token_response(next(tokens))
        if request.url.path == "/rest/v1/data:upload":
            uploads.append(request.headers["authorization"])
            if request.headers["authorization"] == "Bearer old":
                return httpx.Response(401, text="token expired")
            return result({"request_file_id": "file-1"})
        if request.url.path == "/rest/v1/speech:async_recognize":
            return result({"id": "task-1"})
        if request.url.path == "/rest/v1/task:get":
            return result({"status": "DONE", "response_file_id": "result-1"})
        return httpx.Response(200, json=saved_result())

    provider = SaluteSpeechToText(
        salute_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    segments = await provider.transcribe(audio)

    assert uploads == ["Bearer old", "Bearer new"]
    assert len(segments) == 3


async def test_transcribe_raises_on_task_error(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")
    handler = api_handler([], [{"id": "task-1", "status": "ERROR", "error": "bad audio"}])

    provider = SaluteSpeechToText(
        salute_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(SaluteSpeechError, match="bad audio"):
        await provider.transcribe(audio)


async def test_wait_survives_temporary_poll_failures(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")
    polls = iter(["connect", 503, 429, "done"])

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_URL:
            return token_response()
        if request.url.path == "/rest/v1/data:upload":
            return result({"request_file_id": "file-1"})
        if request.url.path == "/rest/v1/speech:async_recognize":
            return result({"id": "task-1"})
        if request.url.path == "/rest/v1/data:download":
            return httpx.Response(200, json=saved_result())
        poll = next(polls)
        if poll == "connect":
            raise httpx.ConnectError("network down", request=request)
        if poll == "done":
            return result({"status": "DONE", "response_file_id": "result-1"})
        return httpx.Response(poll)

    provider = SaluteSpeechToText(
        salute_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    segments = await provider.transcribe(audio)
    assert len(segments) == 3


async def test_wait_stops_at_deadline(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")
    handler = api_handler([], iter(lambda: {"id": "task-1", "status": "RUNNING"}, None))

    provider = SaluteSpeechToText(
        salute_settings(), poll_interval=0, timeout=0, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(SaluteSpeechError, match="task-1"):
        await provider.transcribe(audio)


async def test_upload_error_is_reported(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_URL:
            return token_response()
        return httpx.Response(400, text="invalid audio")

    provider = SaluteSpeechToText(salute_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(SaluteSpeechError, match="invalid audio"):
        await provider.transcribe(audio)


async def test_token_error_is_reported(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="wrong credentials")

    provider = SaluteSpeechToText(salute_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(SaluteSpeechError, match="wrong credentials"):
        await provider.transcribe(audio)


async def test_transcribe_rejects_unsupported_format():
    provider = SaluteSpeechToText(salute_settings())
    with pytest.raises(ValueError, match="lecture.wav"):
        await provider.transcribe(Path("lecture.wav"))


async def test_transcribe_rejects_unknown_language(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    provider = SaluteSpeechToText(salute_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="xx"):
        await provider.transcribe(audio, "xx")
    assert requests == []


def test_ca_bundle_is_added_to_system_certificates():
    system = SaluteSpeechToText(salute_settings())._ssl_context().cert_store_stats()["x509_ca"]
    settings = Settings(
        stt_provider="salute", salute_auth_key="auth-key", salute_ca_bundle=certifi.where()
    )
    with_bundle = SaluteSpeechToText(settings)._ssl_context().cert_store_stats()["x509_ca"]
    assert with_bundle > 0
    assert with_bundle >= system


async def test_repeated_unauthorized_is_reported(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")
    oauth_calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OAUTH_URL:
            oauth_calls.append(request)
            return token_response()
        return httpx.Response(401, text="scope denied")

    provider = SaluteSpeechToText(salute_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(SaluteSpeechError, match="после обновления токена: scope denied"):
        await provider.transcribe(audio)
    assert len(oauth_calls) == 2
