import hashlib
import json
import math
import re
from pathlib import Path

from app.models import EMBEDDING_DIM
from app.providers.base import RecognitionProgress, Segment

STUB_PHRASES = [
    "Сегодня разберём основные понятия курса.",
    "Начнём с определения и простого примера.",
    "Обратите внимание на граничные случаи.",
    "Теперь перейдём к доказательству.",
    "Это часто спрашивают на экзамене.",
    "Подведём итоги лекции.",
]


class StubSpeechToText:
    async def transcribe(
        self,
        audio_path: Path,
        language: str = "ru",
        *,
        duration: float | None = None,
        on_progress: RecognitionProgress | None = None,
    ) -> list[Segment]:
        return [
            Segment(start=i * 10.0, end=i * 10.0 + 9.5, text=phrase)
            for i, phrase in enumerate(STUB_PHRASES)
        ]


STUB_QUIZ_SIZE = 8
STUB_OPTIONS = ["Первый вариант", "Второй вариант", "Третий вариант", "Четвёртый вариант"]


def stub_quiz(user: str) -> str:
    lines = re.findall(r"\[(\d+)\] ([^\n\\]+)", user) or [("0", "")]
    questions = [
        {
            "question": f"Вопрос {number + 1} по лекции",
            "options": STUB_OPTIONS,
            "correct_index": number % len(STUB_OPTIONS),
            "explanation": "Ответ есть в лекции на этом таймкоде.",
            "evidence": lines[number % len(lines)][1],
            "timestamp": int(lines[number % len(lines)][0]),
        }
        for number in range(STUB_QUIZ_SIZE)
    ]
    return json.dumps({"questions": questions}, ensure_ascii=False)


class StubLLM:
    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if json_mode and '"questions"' in system:
            return stub_quiz(user)
        if json_mode:
            return json.dumps({"text": user[:200]}, ensure_ascii=False)
        return f"Кратко: {user[:200]}"


class StubEmbeddings:
    dimension = EMBEDDING_DIM

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode()).digest()
        raw = [seed[i % len(seed)] - 127.5 + i % 7 for i in range(self.dimension)]
        norm = math.sqrt(sum(x * x for x in raw))
        return [x / norm for x in raw]
