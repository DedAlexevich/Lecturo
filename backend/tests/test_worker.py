import json

import httpx
import pytest

from app.core.config import Settings
from app.models import EMBEDDING_DIM
from app.providers.openai_compat import OpenAICompatibleError
from app.worker import WorkerSettings, check_providers, startup

OPENAI_EMBEDDINGS = Settings(
    embeddings_provider="openai",
    embeddings_base_url="https://embeddings.test/v1",
    embeddings_api_key="embeddings-key",
    embeddings_model="bge-m3",
)


def embeddings_transport(dimension: int) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        data = [{"index": index, "embedding": [0.0] * dimension} for index in range(len(texts))]
        return httpx.Response(200, json={"data": data})

    return httpx.MockTransport(handler)


def test_worker_runs_check_on_startup():
    assert WorkerSettings.on_startup is startup


async def test_stub_providers_pass():
    await check_providers(Settings(llm_provider="stub", embeddings_provider="stub"))


async def test_missing_llm_key_fails():
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        await check_providers(Settings(llm_provider="openai", llm_api_key=""))


async def test_missing_embeddings_settings_fail():
    settings = OPENAI_EMBEDDINGS.model_copy(update={"embeddings_api_key": ""})
    with pytest.raises(ValueError, match="EMBEDDINGS_API_KEY"):
        await check_providers(settings)


async def test_embeddings_dimension_matches():
    await check_providers(OPENAI_EMBEDDINGS, embeddings_transport(EMBEDDING_DIM))


async def test_embeddings_dimension_mismatch_fails():
    with pytest.raises(OpenAICompatibleError, match="размерности 768"):
        await check_providers(OPENAI_EMBEDDINGS, embeddings_transport(768))
