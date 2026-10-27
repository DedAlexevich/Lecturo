import json

import httpx
import pytest

from app.core.config import Settings
from app.models import EMBEDDING_DIM
from app.providers import get_embeddings, get_llm, openai_compat
from app.providers.openai_compat import (
    OpenAICompatibleEmbeddings,
    OpenAICompatibleError,
    OpenAICompatibleLLM,
)

SETTINGS = Settings(
    llm_provider="openai",
    llm_base_url="https://llm.test/v1/",
    llm_api_key="llm-key",
    llm_model="deepseek-chat",
    embeddings_provider="openai",
    embeddings_base_url="https://embeddings.test/v1",
    embeddings_api_key="embeddings-key",
    embeddings_model="bge-m3",
)


def chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def embeddings_response(request: httpx.Request, dimension: int = EMBEDDING_DIM) -> httpx.Response:
    texts = json.loads(request.content)["input"]
    data = [
        {"index": index, "embedding": [float(len(text))] * dimension}
        for index, text in reversed(list(enumerate(texts)))
    ]
    return httpx.Response(200, json={"data": data})


def test_factories_return_openai_providers():
    assert isinstance(get_llm(SETTINGS), OpenAICompatibleLLM)
    assert isinstance(get_embeddings(SETTINGS), OpenAICompatibleEmbeddings)


async def test_llm_request_and_json_mode():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return chat_response('{"title": "Введение"}')

    llm = OpenAICompatibleLLM(SETTINGS, transport=httpx.MockTransport(handler))
    assert await llm.complete("система", "текст", json_mode=True) == '{"title": "Введение"}'

    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://llm.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer llm-key"
    assert body["model"] == "deepseek-chat"
    assert body["messages"] == [
        {"role": "system", "content": "система"},
        {"role": "user", "content": "текст"},
    ]
    assert body["response_format"] == {"type": "json_object"}


async def test_llm_retries_on_rate_limit_and_server_error():
    statuses = iter([429, 503])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses, 200)
        return chat_response("готово") if status == 200 else httpx.Response(status)

    llm = OpenAICompatibleLLM(SETTINGS, transport=httpx.MockTransport(handler), retry_delay=0)
    assert await llm.complete("система", "текст") == "готово"


async def test_llm_retries_after_network_error():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("нет сети", request=request)
        return chat_response("готово")

    llm = OpenAICompatibleLLM(SETTINGS, transport=httpx.MockTransport(handler), retry_delay=0)
    assert await llm.complete("система", "текст") == "готово"
    assert calls == 2


async def test_retry_after_is_respected_and_capped(monkeypatch):
    delays = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(openai_compat.asyncio, "sleep", fake_sleep)
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(429, headers={"Retry-After": "3600"}),
            chat_response("готово"),
        ]
    )
    llm = OpenAICompatibleLLM(SETTINGS, transport=httpx.MockTransport(lambda r: next(responses)))
    assert await llm.complete("система", "текст") == "готово"
    assert delays == [7.0, openai_compat.MAX_RETRY_DELAY_SECONDS]


async def test_llm_gives_up_after_attempts():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(502)

    llm = OpenAICompatibleLLM(
        SETTINGS, transport=httpx.MockTransport(handler), attempts=3, retry_delay=0
    )
    with pytest.raises(OpenAICompatibleError):
        await llm.complete("система", "текст")
    assert calls == 3


async def test_llm_does_not_retry_client_error():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "bad key"})

    llm = OpenAICompatibleLLM(SETTINGS, transport=httpx.MockTransport(handler), retry_delay=0)
    with pytest.raises(OpenAICompatibleError):
        await llm.complete("система", "текст")
    assert calls == 1


async def test_embeddings_batches_and_order():
    batches = []

    def handler(request: httpx.Request) -> httpx.Response:
        batches.append(json.loads(request.content)["input"])
        return embeddings_response(request)

    embeddings = OpenAICompatibleEmbeddings(
        SETTINGS, transport=httpx.MockTransport(handler), batch_size=2
    )
    vectors = await embeddings.embed_documents(["а", "бб", "ввв", "гггг", "д"])

    assert batches == [["а", "бб"], ["ввв", "гггг"], ["д"]]
    assert [vector[0] for vector in vectors] == [1.0, 2.0, 3.0, 4.0, 1.0]
    assert all(len(vector) == EMBEDDING_DIM for vector in vectors)


async def test_embeddings_wrong_dimension_from_model():
    transport = httpx.MockTransport(lambda request: embeddings_response(request, dimension=768))
    embeddings = OpenAICompatibleEmbeddings(SETTINGS, transport=transport)
    with pytest.raises(OpenAICompatibleError):
        await embeddings.embed_documents(["текст"])


async def test_embeddings_malformed_response():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"error": "oops"}))
    embeddings = OpenAICompatibleEmbeddings(SETTINGS, transport=transport)
    with pytest.raises(OpenAICompatibleError):
        await embeddings.embed_documents(["текст"])


async def test_non_json_response():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>"))
    llm = OpenAICompatibleLLM(SETTINGS, transport=transport)
    with pytest.raises(OpenAICompatibleError):
        await llm.complete("система", "текст")


def test_missing_settings_fail_on_start():
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        get_llm(SETTINGS.model_copy(update={"llm_api_key": ""}))
    with pytest.raises(ValueError, match="EMBEDDINGS_MODEL"):
        get_embeddings(SETTINGS.model_copy(update={"embeddings_model": ""}))


async def test_requests_share_one_http_client(monkeypatch):
    created = []
    original = httpx.AsyncClient

    def tracking_client(*args, **kwargs):
        client = original(*args, **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", tracking_client)
    embeddings = OpenAICompatibleEmbeddings(
        SETTINGS, transport=httpx.MockTransport(embeddings_response), batch_size=1
    )

    await embeddings.embed_documents(["раз", "два", "три"])

    assert len(created) == 1
