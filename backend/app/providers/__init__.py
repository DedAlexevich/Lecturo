from app.core.config import Settings, get_settings
from app.providers.base import LLM, Embeddings, Segment, SpeechToText
from app.providers.stub import StubEmbeddings, StubLLM, StubSpeechToText
from app.providers.yandex import YandexSpeechToText

__all__ = [
    "LLM",
    "Embeddings",
    "Segment",
    "SpeechToText",
    "get_embeddings",
    "get_llm",
    "get_speech_to_text",
]


def get_speech_to_text(settings: Settings | None = None) -> SpeechToText:
    settings = settings or get_settings()
    match settings.stt_provider:
        case "stub":
            return StubSpeechToText()
        case "yandex":
            return YandexSpeechToText(settings)
    raise ValueError(f"Неизвестный STT_PROVIDER: {settings.stt_provider}")


def get_llm(settings: Settings | None = None) -> LLM:
    settings = settings or get_settings()
    match settings.llm_provider:
        case "stub":
            return StubLLM()
    raise ValueError(f"Неизвестный LLM_PROVIDER: {settings.llm_provider}")


def get_embeddings(settings: Settings | None = None) -> Embeddings:
    settings = settings or get_settings()
    match settings.embeddings_provider:
        case "stub":
            return StubEmbeddings()
    raise ValueError(f"Неизвестный EMBEDDINGS_PROVIDER: {settings.embeddings_provider}")
