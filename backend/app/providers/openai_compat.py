import asyncio
from typing import Any

import httpx

from app.core.config import Settings
from app.models import EMBEDDING_DIM

MAX_RETRY_DELAY_SECONDS = 60.0


class OpenAICompatibleError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        attempts: int = 4,
        retry_delay: float = 1.0,
        timeout: float = 120,
        transport: httpx.AsyncBaseTransport | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.attempts = attempts
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.transport = transport
        self.headers = headers or {"Authorization": f"Bearer {api_key}"}

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            for attempt in range(1, self.attempts + 1):
                try:
                    response = await client.post(
                        f"{self.base_url}{path}", json=body, headers=self.headers
                    )
                except httpx.TransportError as error:
                    if attempt == self.attempts:
                        raise OpenAICompatibleError(f"{path}: нет ответа от API") from error
                    await asyncio.sleep(self._delay(attempt, None))
                    continue
                if response.status_code == 429 or response.is_server_error:
                    if attempt == self.attempts:
                        raise OpenAICompatibleError(
                            f"{path}: API ответил {response.status_code} после {attempt} попыток"
                        )
                    await asyncio.sleep(self._delay(attempt, response))
                    continue
                if response.is_error:
                    raise OpenAICompatibleError(
                        f"{path}: API ответил {response.status_code}: {response.text[:500]}"
                    )
                try:
                    return response.json()
                except ValueError as error:
                    raise OpenAICompatibleError(f"{path}: ответ API не в формате JSON") from error
        raise OpenAICompatibleError(f"{path}: не было ни одной попытки запроса")

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        retry_after = response.headers.get("retry-after", "") if response else ""
        delay = (
            float(retry_after) if retry_after.isdigit() else self.retry_delay * 2 ** (attempt - 1)
        )
        return min(delay, MAX_RETRY_DELAY_SECONDS)


def require_settings(settings: dict[str, str], provider: str) -> None:
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise ValueError(f"Не заданы настройки {provider}: {', '.join(missing)}")


class OpenAICompatibleLLM:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        **options: Any,
    ) -> None:
        require_settings(
            {
                "LLM_BASE_URL": settings.llm_base_url,
                "LLM_API_KEY": settings.llm_api_key,
                "LLM_MODEL": settings.llm_model,
            },
            "LLM",
        )
        self.model = settings.llm_model
        self.max_tokens = settings.llm_max_tokens
        options.setdefault("timeout", settings.llm_timeout)
        self.client = OpenAICompatibleClient(
            settings.llm_base_url, settings.llm_api_key, transport=transport, **options
        )

    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        response = await self.client.post("/chat/completions", body)
        try:
            choice = response["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise OpenAICompatibleError("/chat/completions: в ответе нет текста") from error
        if choice.get("finish_reason") == "length":
            raise OpenAICompatibleError(
                f"/chat/completions: ответ обрезан на лимите {self.max_tokens} токенов, "
                "увеличьте LLM_MAX_TOKENS или сократите запрос"
            )
        if not content:
            raise OpenAICompatibleError("/chat/completions: модель вернула пустой ответ")
        return content


class OpenAICompatibleEmbeddings:
    def __init__(
        self,
        settings: Settings,
        *,
        batch_size: int = 64,
        transport: httpx.AsyncBaseTransport | None = None,
        **options: Any,
    ) -> None:
        require_settings(
            {
                "EMBEDDINGS_BASE_URL": settings.embeddings_base_url,
                "EMBEDDINGS_API_KEY": settings.embeddings_api_key,
                "EMBEDDINGS_MODEL": settings.embeddings_model,
            },
            "эмбеддингов",
        )
        self.dimension = EMBEDDING_DIM
        self.model = settings.embeddings_model
        self.batch_size = batch_size
        self.client = OpenAICompatibleClient(
            settings.embeddings_base_url,
            settings.embeddings_api_key,
            transport=transport,
            **options,
        )

    async def embed_query(self, text: str) -> list[float]:
        [vector] = await self.embed_documents([text])
        return vector

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(await self._embed_batch(texts[start : start + self.batch_size]))
        return vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = await self.client.post("/embeddings", {"model": self.model, "input": texts})
        try:
            items = sorted(response["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in items]
        except (KeyError, TypeError) as error:
            raise OpenAICompatibleError("/embeddings: в ответе нет векторов") from error
        if len(vectors) != len(texts):
            raise OpenAICompatibleError(
                f"/embeddings: отправлено {len(texts)} текстов, получено {len(vectors)} векторов"
            )
        for vector in vectors:
            if len(vector) != self.dimension:
                raise OpenAICompatibleError(
                    f"/embeddings: модель вернула вектор размерности {len(vector)}, "
                    f"ожидалась {self.dimension}"
                )
        return vectors
