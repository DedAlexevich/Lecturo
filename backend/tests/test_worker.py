import pytest

from app.core.config import Settings
from app.models import EMBEDDING_DIM
from app.providers import openai_compat
from app.worker import WorkerSettings, check_providers, startup

OPENAI_EMBEDDINGS = {
    "embeddings_provider": "openai",
    "embeddings_base_url": "https://embeddings.test/v1",
    "embeddings_api_key": "embeddings-key",
    "embeddings_model": "bge-m3",
}


def fake_embed(dimension: int):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * dimension for _ in texts]

    return embed


def test_worker_runs_check_on_startup():
    assert WorkerSettings.on_startup is startup


async def test_stub_providers_pass():
    await check_providers(Settings(llm_provider="stub", embeddings_provider="stub"))


async def test_missing_llm_key_fails():
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        await check_providers(Settings(llm_provider="openai", llm_api_key=""))


async def test_missing_embeddings_settings_fail():
    with pytest.raises(ValueError, match="EMBEDDINGS_API_KEY"):
        await check_providers(Settings(**{**OPENAI_EMBEDDINGS, "embeddings_api_key": ""}))


async def test_embeddings_dimension_matches(monkeypatch):
    monkeypatch.setattr(
        openai_compat.OpenAICompatibleEmbeddings, "embed", fake_embed(EMBEDDING_DIM)
    )
    await check_providers(Settings(**OPENAI_EMBEDDINGS))


async def test_embeddings_dimension_mismatch_fails(monkeypatch):
    monkeypatch.setattr(openai_compat.OpenAICompatibleEmbeddings, "embed", fake_embed(768))
    with pytest.raises(RuntimeError, match="768"):
        await check_providers(Settings(**OPENAI_EMBEDDINGS))
