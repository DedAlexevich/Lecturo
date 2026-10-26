import asyncio
import ssl
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.providers.base import Segment

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
API_URL = "https://smartspeech.sber.ru/rest/v1"
TOKEN_REFRESH_MARGIN_SECONDS = 60

AUDIO_FORMATS = {
    ".opus": ("OPUS", "audio/ogg;codecs=opus"),
    ".ogg": ("OPUS", "audio/ogg;codecs=opus"),
    ".oga": ("OPUS", "audio/ogg;codecs=opus"),
    ".mp3": ("MP3", "audio/mpeg"),
}
LANGUAGE_CODES = {"ru": "ru-RU", "en": "en-US", "kk": "kk-KZ"}


class SaluteSpeechError(RuntimeError):
    pass


def parse_seconds(value: str | float) -> float:
    if isinstance(value, int | float):
        return float(value)
    return float(value.removesuffix("s"))


def parse_recognition(response: list[dict[str, Any]]) -> list[Segment]:
    segments = []
    for utterance in response:
        hypotheses = utterance.get("results") or []
        if not hypotheses:
            continue
        best = hypotheses[0]
        text = (best.get("normalized_text") or best.get("text") or "").strip()
        if not text or "start" not in best or "end" not in best:
            continue
        segments.append(
            Segment(
                start=round(parse_seconds(best["start"]), 3),
                end=round(parse_seconds(best["end"]), 3),
                text=text,
            )
        )
    return sorted(segments, key=lambda segment: (segment.start, segment.end))


class SaluteSpeechToText:
    def __init__(
        self,
        settings: Settings,
        *,
        poll_interval: float = 5.0,
        timeout: float = 6 * 3600,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not settings.salute_auth_key:
            raise ValueError("Не заданы настройки SaluteSpeech: SALUTE_AUTH_KEY")
        self.auth_key = settings.salute_auth_key
        self.scope = settings.salute_scope
        self.ca_bundle = settings.salute_ca_bundle
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.transport = transport
        self._token = ""
        self._token_expires_at = 0.0

    async def transcribe(self, audio_path: Path, language: str = "ru") -> list[Segment]:
        audio_format = AUDIO_FORMATS.get(audio_path.suffix.lower())
        if audio_format is None:
            raise ValueError(f"Формат аудио не поддерживается SaluteSpeech: {audio_path.name}")
        language_code = LANGUAGE_CODES.get(language)
        if language_code is None:
            raise ValueError(f"Язык не поддерживается SaluteSpeech: {language}")
        encoding, content_type = audio_format
        verify: ssl.SSLContext | bool = (
            ssl.create_default_context(cafile=self.ca_bundle) if self.ca_bundle else True
        )
        async with httpx.AsyncClient(
            timeout=120, verify=verify, transport=self.transport
        ) as client:
            file_id = await self._upload(client, audio_path, content_type)
            task_id = await self._start(client, file_id, encoding, language_code)
            response_file_id = await self._wait(client, task_id)
            response = await self._download(client, response_file_id)
        return parse_recognition(response)

    async def _upload(self, client: httpx.AsyncClient, audio_path: Path, content_type: str) -> str:
        content = await asyncio.to_thread(audio_path.read_bytes)
        response = await self._request(
            client,
            "POST",
            "/data:upload",
            "загрузка аудио",
            content=content,
            headers={"Content-Type": content_type},
        )
        return self._field(self._result(response, "загрузка аудио"), "request_file_id")

    async def _start(
        self, client: httpx.AsyncClient, file_id: str, encoding: str, language_code: str
    ) -> str:
        body = {
            "options": {
                "model": "general",
                "audio_encoding": encoding,
                "language": language_code,
                "hypotheses_count": 1,
                "enable_profanity_filter": False,
            },
            "request_file_id": file_id,
        }
        response = await self._request(
            client, "POST", "/speech:async_recognize", "запуск распознавания", json=body
        )
        return self._field(self._result(response, "запуск распознавания"), "id")

    async def _wait(self, client: httpx.AsyncClient, task_id: str) -> str:
        deadline = time.monotonic() + self.timeout
        while True:
            task = await self._fetch_task(client, task_id)
            status = task.get("status")
            if status == "DONE":
                return self._field(task, "response_file_id")
            if status in ("ERROR", "CANCELED"):
                raise SaluteSpeechError(
                    f"Распознавание завершилось со статусом {status}: {task.get('error', '')}"
                )
            if time.monotonic() > deadline:
                raise SaluteSpeechError(f"Распознавание не завершилось: {task_id}")
            await asyncio.sleep(self.poll_interval)

    async def _fetch_task(self, client: httpx.AsyncClient, task_id: str) -> dict[str, Any]:
        try:
            response = await self._request(
                client,
                "GET",
                "/task:get",
                "проверка задачи распознавания",
                params={"id": task_id},
                tolerate_unavailable=True,
            )
        except httpx.TransportError:
            return {}
        if response is None:
            return {}
        return self._result(response, "проверка задачи распознавания")

    async def _download(
        self, client: httpx.AsyncClient, response_file_id: str
    ) -> list[dict[str, Any]]:
        response = await self._request(
            client,
            "GET",
            "/data:download",
            "скачивание результата",
            params={"response_file_id": response_file_id},
        )
        try:
            result = response.json()
        except ValueError as error:
            raise SaluteSpeechError("SaluteSpeech: результат не в формате JSON") from error
        if not isinstance(result, list):
            raise SaluteSpeechError("SaluteSpeech: неожиданный формат результата")
        return result

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        action: str,
        *,
        tolerate_unavailable: bool = False,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        for attempt in (1, 2):
            token = await self._access_token(client)
            response = await client.request(
                method,
                f"{API_URL}{path}",
                headers={**(headers or {}), "Authorization": f"Bearer {token}"},
                **kwargs,
            )
            if response.status_code == 401 and attempt == 1:
                self._token = ""
                continue
            if tolerate_unavailable and (
                response.status_code == 429 or response.is_server_error
            ):
                return None
            self._raise_for_status(response, action)
            return response
        raise SaluteSpeechError(f"SaluteSpeech: {action} отклонена после обновления токена")

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._token_expires_at - TOKEN_REFRESH_MARGIN_SECONDS:
            return self._token
        response = await client.post(
            OAUTH_URL,
            data={"scope": self.scope},
            headers={
                "Authorization": f"Basic {self.auth_key}",
                "RqUID": str(uuid.uuid4()),
                "Accept": "application/json",
            },
        )
        self._raise_for_status(response, "получение токена")
        try:
            payload = response.json()
            self._token = payload["access_token"]
            self._token_expires_at = payload["expires_at"] / 1000
        except (ValueError, KeyError, TypeError) as error:
            raise SaluteSpeechError("SaluteSpeech: в ответе нет токена") from error
        return self._token

    def _result(self, response: httpx.Response, action: str) -> dict[str, Any]:
        try:
            result = response.json()["result"]
        except (ValueError, KeyError, TypeError) as error:
            raise SaluteSpeechError(f"SaluteSpeech: {action} вернула неожиданный ответ") from error
        if not isinstance(result, dict):
            raise SaluteSpeechError(f"SaluteSpeech: {action} вернула неожиданный ответ")
        return result

    def _field(self, result: dict[str, Any], name: str) -> str:
        value = result.get(name)
        if not value:
            raise SaluteSpeechError(f"SaluteSpeech: в ответе нет поля {name}")
        return value

    def _raise_for_status(self, response: httpx.Response, action: str) -> None:
        if response.is_error:
            raise SaluteSpeechError(
                f"SaluteSpeech: {action} вернула {response.status_code}: {response.text[:500]}"
            )
