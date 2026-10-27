import asyncio
import contextlib
import hashlib
import hmac
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.models import EMBEDDING_DIM, StepName
from app.pipeline.estimate import expected_seconds
from app.providers.audio_chunks import (
    CHUNK_CONCURRENCY,
    MAX_CHUNK_SECONDS,
    AudioChunkError,
    split_audio,
)
from app.providers.base import RecognitionProgress, Segment
from app.providers.openai_compat import (
    OpenAICompatibleClient,
    OpenAICompatibleError,
    require_settings,
)
from app.providers.retry import RetryPolicy, request_with_retry

RECOGNIZE_URL = "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize"
OPERATION_URL = "https://operation.api.cloud.yandex.net/operations/{operation_id}"
TEXT_EMBEDDING_PATH = "/foundationModels/v1/textEmbedding"
DOCUMENT_MODEL = "text-search-doc"
QUERY_MODEL = "text-search-query"
EMBEDDINGS_CONCURRENCY = 4
STORAGE_HOST = "storage.yandexcloud.net"
STORAGE_REGION = "ru-central1"
UPLOAD_SHARE = 0.05
RECOGNIZE_LIMIT = 0.95
logger = logging.getLogger(__name__)

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


class YandexNetworkError(YandexSpeechKitError):
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


def merge_chunk_segments(chunks: list[tuple[float, list[Segment]]]) -> list[Segment]:
    segments = sorted(
        (
            Segment(segment.start + offset, segment.end + offset, segment.text)
            for offset, chunk in chunks
            for segment in chunk
        ),
        key=lambda segment: (segment.start, segment.end),
    )
    merged: list[Segment] = []
    last_by_text: dict[str, int] = {}
    for segment in segments:
        normalized = re.sub(r"\W+", "", segment.text.casefold())
        duplicate = last_by_text.get(normalized)
        if duplicate is not None and not (
            merged[duplicate].end >= segment.start - 0.75
            and merged[duplicate].start <= segment.end + 0.75
        ):
            duplicate = None
        if duplicate is None:
            merged.append(segment)
            last_by_text[normalized] = len(merged) - 1
        elif segment.end - segment.start > merged[duplicate].end - merged[duplicate].start:
            merged[duplicate] = segment
    return sorted(merged, key=lambda segment: (segment.start, segment.end))


class YandexSpeechToText:
    def __init__(
        self,
        settings: Settings,
        *,
        poll_interval: float | None = None,
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
        self.poll_interval = settings.stt_poll_seconds if poll_interval is None else poll_interval
        self.settings = settings
        self.timeout = timeout
        self.transport = transport
        self.retry = RetryPolicy.from_settings(settings)

    async def transcribe(
        self,
        audio_path: Path,
        language: str = "ru",
        *,
        duration: float | None = None,
        on_progress: RecognitionProgress | None = None,
    ) -> list[Segment]:
        suffix = audio_path.suffix.lower()
        encoding = AUDIO_ENCODINGS.get(suffix)
        if encoding is None:
            raise ValueError(f"Формат аудио не поддерживается SpeechKit: {audio_path.name}")
        language_code = LANGUAGE_CODES.get(language)
        if language_code is None:
            raise ValueError(f"Язык не поддерживается SpeechKit: {language}")
        async with httpx.AsyncClient(timeout=120, transport=self.transport) as client:
            if duration is not None and duration > MAX_CHUNK_SECONDS:
                with TemporaryDirectory(prefix="lecturo-stt-", dir=audio_path.parent) as temp_dir:
                    await self._notify(on_progress, "split", 0.0)
                    try:
                        chunks = await split_audio(audio_path, duration, Path(temp_dir))
                    except AudioChunkError:
                        logger.warning(
                            "Не удалось разделить аудио; отправляем запись целиком", exc_info=True
                        )
                        chunks = []
                    if chunks:
                        await self._notify(on_progress, "upload", UPLOAD_SHARE)
                        results = await self._transcribe_chunks(
                            client, chunks, encoding, language_code, on_progress
                        )
                        await self._notify(on_progress, "fetch", RECOGNIZE_LIMIT)
                        return merge_chunk_segments(results)
            return await self._transcribe_file(
                client, audio_path, encoding, language_code, duration, on_progress
            )

    async def _transcribe_chunks(
        self,
        client: httpx.AsyncClient,
        chunks: list[tuple[Path, float]],
        encoding: str,
        language_code: str,
        on_progress: RecognitionProgress | None,
    ) -> list[tuple[float, list[Segment]]]:
        semaphore = asyncio.Semaphore(CHUNK_CONCURRENCY)
        progress_lock = asyncio.Lock()
        completed = 0

        async def transcribe_chunk(path: Path, offset: float) -> tuple[float, list[Segment]]:
            nonlocal completed
            async with semaphore:
                segments = await self._transcribe_file(
                    client, path, encoding, language_code, None, None
                )
            async with progress_lock:
                completed += 1
                await self._notify(
                    on_progress,
                    "recognize",
                    UPLOAD_SHARE + (RECOGNIZE_LIMIT - UPLOAD_SHARE) * completed / len(chunks),
                )
            return offset, segments

        results = await asyncio.gather(
            *(transcribe_chunk(path, offset) for path, offset in chunks), return_exceptions=True
        )
        error = next((result for result in results if isinstance(result, BaseException)), None)
        if error is not None:
            raise error
        return cast(list[tuple[float, list[Segment]]], results)

    async def _transcribe_file(
        self,
        client: httpx.AsyncClient,
        audio_path: Path,
        encoding: str,
        language_code: str,
        duration: float | None,
        on_progress: RecognitionProgress | None,
    ) -> list[Segment]:
        key = f"stt/{uuid.uuid4().hex}{audio_path.suffix.lower()}"
        await self._notify(on_progress, "upload", 0.0)
        await self._upload(client, audio_path, key)
        try:
            await self._notify(on_progress, "recognize", UPLOAD_SHARE)
            operation_id = await self._start(client, key, encoding, language_code)
            response = await self._wait(client, operation_id, duration, on_progress)
        finally:
            await self._delete(client, key)
        await self._notify(on_progress, "fetch", RECOGNIZE_LIMIT)
        return parse_recognition(response)

    async def _notify(
        self, on_progress: RecognitionProgress | None, stage: str, fraction: float
    ) -> None:
        if on_progress is not None:
            await on_progress(stage, fraction)

    def expected_seconds(self, duration: float | None) -> float | None:
        return expected_seconds(StepName.transcribe, duration, self.settings)

    async def _upload(self, client: httpx.AsyncClient, audio_path: Path, key: str) -> None:
        content = await asyncio.to_thread(audio_path.read_bytes)
        payload_hash = hashlib.sha256(content).hexdigest()
        response = await self._send(
            "загрузка аудио в Object Storage",
            lambda: client.put(
                self._object_url(key),
                content=content,
                headers=self._storage_headers("PUT", key, payload_hash),
            ),
        )
        self._raise_for_status(response, "загрузка аудио в Object Storage")

    async def _delete(self, client: httpx.AsyncClient, key: str) -> None:
        payload_hash = hashlib.sha256(b"").hexdigest()
        with contextlib.suppress(httpx.HTTPError):
            await client.delete(
                self._object_url(key), headers=self._storage_headers("DELETE", key, payload_hash)
            )

    async def _start(
        self, client: httpx.AsyncClient, key: str, encoding: str, language_code: str
    ) -> str:
        body: dict[str, Any] = {
            "config": {
                "specification": {
                    "languageCode": language_code,
                    "model": "general",
                    "audioEncoding": encoding,
                    "literature_text": True,
                }
            },
            "audio": {"uri": self._object_url(key)},
        }
        if self.folder_id:
            body["config"]["folderId"] = self.folder_id
        response = await self._send(
            "запуск распознавания",
            lambda: client.post(RECOGNIZE_URL, json=body, headers=self._api_headers()),
        )
        self._raise_for_status(response, "запуск распознавания")
        return response.json()["id"]

    async def _wait(
        self,
        client: httpx.AsyncClient,
        operation_id: str,
        duration: float | None = None,
        on_progress: RecognitionProgress | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        deadline = started + self.timeout
        expected = self.expected_seconds(duration)
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
            if expected is not None:
                share = min((time.monotonic() - started) / expected, 1.0)
                await self._notify(
                    on_progress,
                    "recognize",
                    UPLOAD_SHARE + (RECOGNIZE_LIMIT - UPLOAD_SHARE) * share,
                )
            await asyncio.sleep(self.poll_interval)

    async def _fetch_operation(self, client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        try:
            response = await self._send(
                "проверка операции распознавания",
                lambda: client.get(url, headers=self._api_headers()),
            )
        except YandexNetworkError:
            return {}
        if response.status_code == 429 or response.is_server_error:
            return {}
        self._raise_for_status(response, "проверка операции распознавания")
        return response.json()

    async def _send(
        self, action: str, send: Callable[[], Awaitable[httpx.Response]]
    ) -> httpx.Response:
        return await request_with_retry(
            send,
            policy=self.retry,
            provider="Yandex SpeechKit",
            action=action,
            error_cls=YandexNetworkError,
        )

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


class YandexEmbeddings:
    def __init__(
        self,
        settings: Settings,
        *,
        concurrency: int = EMBEDDINGS_CONCURRENCY,
        transport: httpx.AsyncBaseTransport | None = None,
        **options: Any,
    ) -> None:
        api_key = settings.yandex_embeddings_api_key or settings.yandex_speechkit_api_key
        folder_id = settings.yandex_embeddings_folder_id or settings.yandex_folder_id
        require_settings(
            {
                "YANDEX_EMBEDDINGS_API_KEY или YANDEX_SPEECHKIT_API_KEY": api_key,
                "YANDEX_EMBEDDINGS_FOLDER_ID или YANDEX_FOLDER_ID": folder_id,
            },
            "эмбеддингов Yandex",
        )
        self.dimension = EMBEDDING_DIM
        self.folder_id = folder_id
        self.semaphore = asyncio.Semaphore(concurrency)
        self.client = OpenAICompatibleClient(
            settings.yandex_embeddings_base_url,
            api_key,
            transport=transport,
            headers={"Authorization": f"Api-Key {api_key}", "x-folder-id": folder_id},
            **options,
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return list(await asyncio.gather(*(self._embed(DOCUMENT_MODEL, text) for text in texts)))

    async def embed_query(self, text: str) -> list[float]:
        return await self._embed(QUERY_MODEL, text)

    async def _embed(self, model: str, text: str) -> list[float]:
        body = {"modelUri": f"emb://{self.folder_id}/{model}/latest", "text": text}
        async with self.semaphore:
            response = await self.client.post(TEXT_EMBEDDING_PATH, body)
        vector = response.get("embedding")
        if not isinstance(vector, list):
            raise OpenAICompatibleError(f"{TEXT_EMBEDDING_PATH}: в ответе нет вектора")
        if len(vector) != self.dimension:
            raise OpenAICompatibleError(
                f"{TEXT_EMBEDDING_PATH}: модель вернула вектор размерности {len(vector)}, "
                f"ожидалась {self.dimension}"
            )
        return [float(value) for value in vector]
