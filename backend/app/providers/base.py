from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


RecognitionProgress = Callable[[str, float], Awaitable[None]]


class OperationStore(Protocol):
    async def load(self, name: str) -> dict[str, str] | None: ...

    async def save(self, name: str, state: dict[str, str]) -> None: ...

    async def drop(self, name: str) -> None: ...

    async def alive(self) -> bool: ...


class SpeechToText(Protocol):
    async def transcribe(
        self,
        audio_path: Path,
        language: str = "ru",
        *,
        duration: float | None = None,
        on_progress: RecognitionProgress | None = None,
        operations: OperationStore | None = None,
    ) -> list[Segment]: ...

    async def discard(self, object_keys: list[str]) -> None: ...


class LLM(Protocol):
    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str: ...


class Embeddings(Protocol):
    dimension: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...
