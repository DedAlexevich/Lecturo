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
