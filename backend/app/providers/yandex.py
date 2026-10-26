import asyncio
import contextlib
import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.providers.base import Segment

RECOGNIZE_URL = "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize"
OPERATION_URL = "https://operation.api.cloud.yandex.net/operations/{operation_id}"
STORAGE_HOST = "storage.yandexcloud.net"
STORAGE_REGION = "ru-central1"

AUDIO_ENCODINGS = {".opus": "OGG_OPUS", ".ogg": "OGG_OPUS", ".oga": "OGG_OPUS", ".mp3": "MP3"}
LANGUAGE_CODES = {
    "ru": "ru-RU",
    "en": "en-US",
    "de": "de-DE",
    "fr": "fr-FR",
    "es": "es-ES",
    "it": "it-IT",
    "kk": "kk-KZ",
    "uz": "uz-UZ",
    "tr": "tr-TR",
}


class YandexSpeechKitError(RuntimeError):
    pass


def parse_seconds(value: str) -> float:
    return float(value.removesuffix("s"))


def parse_recognition(response: dict[str, Any]) -> list[Segment]:
    segments = []
    for chunk in response.get("chunks", []):
        alternatives = chunk.get("alternatives") or []
        if not alternatives:
            continue
        best = alternatives[0]
        text = best.get("text", "").strip()
        words = best.get("words") or []
        if not text or not words:
            continue
        segments.append(
            Segment(
                start=round(parse_seconds(words[0]["startTime"]), 3),
                end=round(parse_seconds(words[-1]["endTime"]), 3),
                text=text,
            )
        )
    return sorted(segments, key=lambda segment: (segment.start, segment.end))


class YandexSpeechToText:
    def __init__(
        self,
        settings: Settings,
        *,
        poll_interval: float = 5.0,
        timeout: float = 6 * 3600,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        required = {
            "YANDEX_SPEECHKIT_API_KEY": settings.yandex_speechkit_api_key,
            "YANDEX_STORAGE_BUCKET": settings.yandex_storage_bucket,
            "YANDEX_STORAGE_ACCESS_KEY": settings.yandex_storage_access_key,
            "YANDEX_STORAGE_SECRET_KEY": settings.yandex_storage_secret_key,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Не заданы настройки Yandex SpeechKit: {', '.join(missing)}")
        self.api_key = settings.yandex_speechkit_api_key
        self.folder_id = settings.yandex_folder_id
        self.bucket = settings.yandex_storage_bucket
        self.access_key = settings.yandex_storage_access_key
        self.secret_key = settings.yandex_storage_secret_key
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.transport = transport

    async def transcribe(self, audio_path: Path, language: str = "ru") -> list[Segment]:
        suffix = audio_path.suffix.lower()
        encoding = AUDIO_ENCODINGS.get(suffix)
        if encoding is None:
            raise ValueError(f"Формат аудио не поддерживается SpeechKit: {audio_path.name}")
        key = f"stt/{uuid.uuid4().hex}{suffix}"
        async with httpx.AsyncClient(timeout=120, transport=self.transport) as client:
            await self._upload(client, audio_path, key)
            try:
                operation_id = await self._start(client, key, encoding, language)
                response = await self._wait(client, operation_id)
            finally:
                await self._delete(client, key)
        return parse_recognition(response)

    async def _upload(self, client: httpx.AsyncClient, audio_path: Path, key: str) -> None:
        content = await asyncio.to_thread(audio_path.read_bytes)
        payload_hash = hashlib.sha256(content).hexdigest()
        response = await client.put(
            self._object_url(key),
            content=content,
            headers=self._storage_headers("PUT", key, payload_hash),
        )
        self._raise_for_status(response, "загрузка аудио в Object Storage")

    async def _delete(self, client: httpx.AsyncClient, key: str) -> None:
        payload_hash = hashlib.sha256(b"").hexdigest()
        with contextlib.suppress(httpx.HTTPError):
            await client.delete(
                self._object_url(key), headers=self._storage_headers("DELETE", key, payload_hash)
            )

    async def _start(
        self, client: httpx.AsyncClient, key: str, encoding: str, language: str
    ) -> str:
        body: dict[str, Any] = {
            "config": {
                "specification": {
                    "languageCode": LANGUAGE_CODES.get(language, language),
                    "model": "general",
                    "audioEncoding": encoding,
                    "literature_text": True,
                }
            },
            "audio": {"uri": self._object_url(key)},
        }
        if self.folder_id:
            body["config"]["folderId"] = self.folder_id
        response = await client.post(RECOGNIZE_URL, json=body, headers=self._api_headers())
        self._raise_for_status(response, "запуск распознавания")
        return response.json()["id"]

    async def _wait(self, client: httpx.AsyncClient, operation_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        url = OPERATION_URL.format(operation_id=operation_id)
        while True:
            operation = await self._fetch_operation(client, url)
            if operation.get("done"):
                if "error" in operation:
                    error = operation["error"]
                    raise YandexSpeechKitError(
                        f"Распознавание завершилось ошибкой: {error.get('message', error)}"
                    )
                return operation.get("response", {})
            if time.monotonic() > deadline:
                raise YandexSpeechKitError(f"Распознавание не завершилось: {operation_id}")
            await asyncio.sleep(self.poll_interval)

    async def _fetch_operation(self, client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        try:
            response = await client.get(url, headers=self._api_headers())
        except httpx.TransportError:
            return {}
        if response.status_code == 429 or response.is_server_error:
            return {}
        self._raise_for_status(response, "проверка операции распознавания")
        return response.json()

    def _api_headers(self) -> dict[str, str]:
        return {"Authorization": f"Api-Key {self.api_key}"}

    def _object_path(self, key: str) -> str:
        return f"/{self.bucket}/{quote(key)}"

    def _object_url(self, key: str) -> str:
        return f"https://{STORAGE_HOST}{self._object_path(key)}"

    def _storage_headers(self, method: str, key: str, payload_hash: str) -> dict[str, str]:
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date = now.strftime("%Y%m%d")
        headers = {
            "host": STORAGE_HOST,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        signed_headers = ";".join(sorted(headers))
        canonical_request = "\n".join(
            [
                method,
                self._object_path(key),
                "",
                *(f"{name}:{headers[name]}" for name in sorted(headers)),
                "",
                signed_headers,
                payload_hash,
            ]
        )
        scope = f"{date}/{STORAGE_REGION}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signing_key = f"AWS4{self.secret_key}".encode()
        for part in (date, STORAGE_REGION, "s3", "aws4_request"):
            signing_key = hmac.new(signing_key, part.encode(), hashlib.sha256).digest()
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return headers

    def _raise_for_status(self, response: httpx.Response, action: str) -> None:
        if response.is_error:
            raise YandexSpeechKitError(
                f"Yandex SpeechKit: {action} вернула {response.status_code}: {response.text[:500]}"
            )
