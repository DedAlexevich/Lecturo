import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.models import EMBEDDING_DIM
from app.providers import get_embeddings
from app.providers.openai_compat import OpenAICompatibleError
from app.providers.yandex import YandexEmbeddings
from app.worker import check_providers

SETTINGS = Settings(
    embeddings_provider="yandex",
    yandex_speechkit_api_key="speech-key",
    yandex_folder_id="folder-1",
)


def vector_response(dimension: int = EMBEDDING_DIM, value: float = 0.5) -> httpx.Response:
    return httpx.Response(
        200, json={"embedding": [value] * dimension, "numTokens": "3", "modelVersion": "1"}
    )


def make(handler, settings: Settings = SETTINGS, **options) -> YandexEmbeddings:
    return YandexEmbeddings(
        settings, transport=httpx.MockTransport(handler), retry_delay=0, **options
    )


def test_factory_returns_yandex_provider():
    assert isinstance(get_embeddings(SETTINGS), YandexEmbeddings)


def test_dimension_is_256():
    assert EMBEDDING_DIM == 256
    assert get_embeddings(SETTINGS).dimension == 256


async def test_documents_and_query_use_different_models():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return vector_response()

    embeddings = make(handler)
    vectors = await embeddings.embed_documents(["один", "два"])
    query = await embeddings.embed_query("вопрос")

    assert len(vectors) == 2
    assert all(len(vector) == 256 for vector in [*vectors, query])
    bodies = [json.loads(request.content) for request in requests]
    assert sorted(body["text"] for body in bodies[:2]) == ["два", "один"]
    assert {body["modelUri"] for body in bodies[:2]} == {"emb://folder-1/text-search-doc/latest"}
    assert bodies[2] == {"modelUri": "emb://folder-1/text-search-query/latest", "text": "вопрос"}
    assert requests[0].method == "POST"
    assert str(requests[0].url) == (
        "https://ai.api.cloud.yandex.net/foundationModels/v1/textEmbedding"
    )
    assert requests[0].headers["authorization"] == "Api-Key speech-key"
    assert requests[0].headers["x-folder-id"] == "folder-1"


async def test_documents_keep_input_order():
    def handler(request: httpx.Request) -> httpx.Response:
        return vector_response(value=float(len(json.loads(request.content)["text"])))

    vectors = await make(handler).embed_documents(["а", "бб", "ввв"])

    assert [vector[0] for vector in vectors] == [1.0, 2.0, 3.0]


async def test_separate_key_and_folder_take_priority():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return vector_response()

    settings = SETTINGS.model_copy(
        update={"yandex_embeddings_api_key": "emb-key", "yandex_embeddings_folder_id": "folder-2"}
    )
    await make(handler, settings).embed_query("q")

    assert seen[0].headers["authorization"] == "Api-Key emb-key"
    assert json.loads(seen[0].content)["modelUri"].startswith("emb://folder-2/")


async def test_retries_on_rate_limit_and_server_error():
    statuses = iter([429, 503, 200])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        status = next(statuses)
        return vector_response() if status == 200 else httpx.Response(status)

    vector = await make(handler).embed_query("q")

    assert len(vector) == 256
    assert len(calls) == 3


async def test_gives_up_after_attempts():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429)

    with pytest.raises(OpenAICompatibleError, match="429"):
        await make(handler, attempts=3).embed_query("q")

    assert len(calls) == 3


async def test_auth_error_is_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(403, text="Permission denied")

    with pytest.raises(OpenAICompatibleError, match="403"):
        await make(handler).embed_query("q")

    assert len(calls) == 1


async def test_wrong_dimension_fails():
    with pytest.raises(OpenAICompatibleError, match="размерности 768"):
        await make(lambda request: vector_response(768)).embed_query("q")


async def test_response_without_vector_fails():
    with pytest.raises(OpenAICompatibleError, match="нет вектора"):
        await make(lambda request: httpx.Response(200, json={})).embed_query("q")


async def test_limits_parallel_requests():
    active = 0
    peak = 0

    class SlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return vector_response()

    embeddings = YandexEmbeddings(SETTINGS, transport=SlowTransport(), concurrency=2)
    await embeddings.embed_documents([str(number) for number in range(8)])

    assert peak == 2


def test_missing_key_or_folder_fails():
    with pytest.raises(ValueError, match="YANDEX_SPEECHKIT_API_KEY"):
        get_embeddings(Settings(embeddings_provider="yandex", yandex_folder_id="f"))
    with pytest.raises(ValueError, match="YANDEX_FOLDER_ID"):
        get_embeddings(Settings(embeddings_provider="yandex", yandex_speechkit_api_key="k"))


async def test_startup_check_passes():
    await check_providers(SETTINGS, httpx.MockTransport(lambda request: vector_response()))


async def test_startup_check_reports_bad_key_without_retries():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, text="Unknown api key")

    with pytest.raises(OpenAICompatibleError, match="401"):
        await check_providers(SETTINGS, httpx.MockTransport(handler))

    assert len(calls) == 1
