import json
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.providers import Segment, get_speech_to_text
from app.providers.yandex import (
    RECOGNIZE_URL,
    YandexSpeechKitError,
    YandexSpeechToText,
    parse_recognition,
)

FIXTURE = Path(__file__).parent / "fixtures" / "yandex_stt_operation.json"


def yandex_settings() -> Settings:
    return Settings(
        stt_provider="yandex",
        yandex_speechkit_api_key="api-key",
        yandex_folder_id="folder",
        yandex_storage_bucket="lecturo-audio",
        yandex_storage_access_key="access",
        yandex_storage_secret_key="secret",
    )


def saved_operation() -> dict:
    return json.loads(FIXTURE.read_text())


def test_parse_recognition_from_saved_response():
    segments = parse_recognition(saved_operation()["response"])

    assert segments == [
        Segment(start=0.88, end=2.4, text="Сегодня разберём производные."),
        Segment(start=3.16, end=4.66, text="Начнём с определения."),
        Segment(start=65.3, end=66.42, text="Пример первый."),
    ]
    assert all(s.start <= s.end for s in segments)
    assert all(a.end <= b.start for a, b in zip(segments, segments[1:], strict=False))


def test_parse_recognition_empty_response():
    assert parse_recognition({}) == []


def stereo_chunk(channel: str, start: str, end: str, text: str) -> dict:
    words = [{"startTime": start, "endTime": end, "word": text.lower(), "confidence": 1}]
    return {"alternatives": [{"words": words, "text": text}], "channelTag": channel}


def test_parse_recognition_keeps_one_channel_of_stereo_audio():
    response = {
        "chunks": [
            stereo_chunk("1", "41.2s", "44.8s", "Надуть, перекрыть выход воздуха."),
            stereo_chunk("2", "41.2s", "44.8s", "Надуть, перекрыть выход воздуха."),
            stereo_chunk("2", "45.1s", "47s", "Подключить к лопастям."),
            stereo_chunk("1", "45.1s", "47s", "Подключить к лопастям."),
        ]
    }

    assert parse_recognition(response) == [
        Segment(start=41.2, end=44.8, text="Надуть, перекрыть выход воздуха."),
        Segment(start=45.1, end=47.0, text="Подключить к лопастям."),
    ]


def test_factory_returns_yandex_provider():
    assert isinstance(get_speech_to_text(yandex_settings()), YandexSpeechToText)


def test_factory_requires_credentials():
    with pytest.raises(ValueError, match="YANDEX_SPEECHKIT_API_KEY"):
        get_speech_to_text(Settings(stt_provider="yandex"))


async def test_transcribe_uploads_polls_and_cleans_up(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS-audio")
    requests: list[httpx.Request] = []
    polls = iter([{"id": "op1", "done": False}, saved_operation()])

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "storage.yandexcloud.net":
            return httpx.Response(200)
        if str(request.url) == RECOGNIZE_URL:
            return httpx.Response(200, json={"id": "op1", "done": False})
        return httpx.Response(200, json=next(polls))

    provider = YandexSpeechToText(
        yandex_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    segments = await provider.transcribe(audio, "ru")

    assert [s.text for s in segments][0] == "Сегодня разберём производные."
    upload, start, *_, delete = requests
    assert upload.method == "PUT"
    assert upload.url.path.startswith("/lecturo-audio/stt/")
    assert upload.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=access/")
    assert upload.content == b"OggS-audio"
    body = json.loads(start.content)
    assert start.headers["authorization"] == "Api-Key api-key"
    assert body["config"]["specification"]["languageCode"] == "ru-RU"
    assert body["config"]["specification"]["audioEncoding"] == "OGG_OPUS"
    assert body["config"]["folderId"] == "folder"
    assert body["audio"]["uri"] == str(upload.url)
    assert [r.url.path for r in requests[2:-1]] == ["/operations/op1", "/operations/op1"]
    assert delete.method == "DELETE"
    assert delete.url == upload.url


async def test_transcribe_raises_on_operation_error(tmp_path: Path):
    audio = tmp_path / "lecture.mp3"
    audio.write_bytes(b"ID3")
    deleted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            deleted.append(request.url.path)
        if request.url.host == "storage.yandexcloud.net":
            return httpx.Response(200)
        if str(request.url) == RECOGNIZE_URL:
            return httpx.Response(200, json={"id": "op2", "done": False})
        return httpx.Response(
            200, json={"id": "op2", "done": True, "error": {"code": 3, "message": "bad audio"}}
        )

    provider = YandexSpeechToText(
        yandex_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(YandexSpeechKitError, match="bad audio"):
        await provider.transcribe(audio)
    assert len(deleted) == 1


async def test_transcribe_rejects_unsupported_format():
    provider = YandexSpeechToText(yandex_settings())
    with pytest.raises(ValueError, match="lecture.wav"):
        await provider.transcribe(Path("lecture.wav"))


async def test_transcribe_keeps_result_when_cleanup_fails(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            raise httpx.ConnectError("storage unavailable", request=request)
        if request.url.host == "storage.yandexcloud.net":
            return httpx.Response(200)
        if str(request.url) == RECOGNIZE_URL:
            return httpx.Response(200, json={"id": "op3", "done": False})
        return httpx.Response(200, json=saved_operation())

    provider = YandexSpeechToText(
        yandex_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    segments = await provider.transcribe(audio)
    assert len(segments) == 3


async def test_transcribe_error_not_replaced_by_cleanup_error(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(500)
        if request.url.host == "storage.yandexcloud.net":
            return httpx.Response(200)
        return httpx.Response(400, text="invalid config")

    provider = YandexSpeechToText(
        yandex_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(YandexSpeechKitError, match="invalid config"):
        await provider.transcribe(audio)


async def test_wait_survives_temporary_poll_failures(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")
    polls = iter(["connect", 503, 429, "done"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "storage.yandexcloud.net":
            return httpx.Response(200)
        if str(request.url) == RECOGNIZE_URL:
            return httpx.Response(200, json={"id": "op4", "done": False})
        poll = next(polls)
        if poll == "connect":
            raise httpx.ConnectError("network down", request=request)
        if poll == "done":
            return httpx.Response(200, json=saved_operation())
        return httpx.Response(poll)

    provider = YandexSpeechToText(
        yandex_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    segments = await provider.transcribe(audio)
    assert len(segments) == 3


async def test_wait_stops_at_deadline_on_persistent_failures(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "storage.yandexcloud.net":
            return httpx.Response(200)
        if str(request.url) == RECOGNIZE_URL:
            return httpx.Response(200, json={"id": "op5", "done": False})
        return httpx.Response(502)

    provider = YandexSpeechToText(
        yandex_settings(), poll_interval=0, timeout=0, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(YandexSpeechKitError, match="op5"):
        await provider.transcribe(audio)


async def test_wait_fails_on_client_error(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "storage.yandexcloud.net":
            return httpx.Response(200)
        if str(request.url) == RECOGNIZE_URL:
            return httpx.Response(200, json={"id": "op6", "done": False})
        return httpx.Response(403, text="permission denied")

    provider = YandexSpeechToText(
        yandex_settings(), poll_interval=0, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(YandexSpeechKitError, match="permission denied"):
        await provider.transcribe(audio)


async def test_transcribe_rejects_unknown_language(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    provider = YandexSpeechToText(yandex_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="xx"):
        await provider.transcribe(audio, "xx")
    assert requests == []
