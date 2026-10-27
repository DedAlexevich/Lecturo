import json
import math
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.models import ChunkKind
from app.providers.base import LLM
from app.schemas.search import SearchHit

PROMPT = (Path(__file__).parent.parent / "pipeline/prompts/lecture_chat.md").read_text(
    encoding="utf-8"
)
MAX_SOURCES = 12
MAX_SOURCE_LENGTH = 2000
MAX_CONTEXT_LENGTH = 12000
MAX_HISTORY_MESSAGES = 8
MAX_HISTORY_LENGTH = 1000


@dataclass(frozen=True)
class ChatSource:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ChatReply:
    related: bool
    lecture_answer: str
    additional: str
    sources: list[ChatSource]


class InvalidChatReply(ValueError):
    pass


def select_sources(lecture_id: uuid.UUID, hits: list[SearchHit]) -> list[ChatSource]:
    sources = []
    for hit in hits:
        if (
            hit.lecture_id != lecture_id
            or hit.kind not in {ChunkKind.transcript, ChunkKind.chapter}
            or hit.start is None
            or hit.end is None
            or not math.isfinite(hit.start)
            or not math.isfinite(hit.end)
            or hit.start < 0
            or hit.end < hit.start
            or not hit.text.strip()
        ):
            continue
        sources.append(ChatSource(hit.start, hit.end, hit.text[:MAX_SOURCE_LENGTH]))
        if len(sources) == MAX_SOURCES:
            break
    return sources


def parse_reply(content: str, sources: list[ChatSource]) -> ChatReply:
    try:
        data = json.loads(content)
    except (TypeError, ValueError) as error:
        raise InvalidChatReply("Ответ модели не является JSON") from error
    if not isinstance(data, dict):
        raise InvalidChatReply("Ответ модели имеет неверный формат")
    related = data.get("related")
    answer = data.get("lecture_answer")
    additional = data.get("additional")
    source_ids = data.get("source_ids")
    if (
        not isinstance(related, bool)
        or not isinstance(answer, str)
        or not isinstance(additional, str)
        or not isinstance(source_ids, list)
        or any(type(index) is not int or index < 1 or index > len(sources) for index in source_ids)
    ):
        raise InvalidChatReply("Ответ модели имеет неверный формат")
    answer = answer.strip()
    additional = additional.strip()
    if not related:
        return ChatReply(False, "", "", [])
    if answer and not source_ids:
        raise InvalidChatReply("Ответ по лекции не содержит источников")
    if not answer and not additional:
        raise InvalidChatReply("Пустой ответ модели")
    selected = [sources[index - 1] for index in dict.fromkeys(source_ids)] if answer else []
    return ChatReply(True, answer, additional, selected)


async def answer_question(
    llm: LLM,
    *,
    lecture_id: uuid.UUID,
    title: str,
    question: str,
    history: list[dict[str, str]],
    summary: str,
    chapters: list[dict[str, str]],
    hits: list[SearchHit],
) -> ChatReply:
    sources = select_sources(lecture_id, hits)
    if not sources:
        return ChatReply(True, "", "В материалах лекции не найден ответ на этот вопрос.", [])
    context = {
        "title": title,
        "question": question,
        "history": [
            {"role": item["role"], "content": item["content"][:MAX_HISTORY_LENGTH]}
            for item in history[-MAX_HISTORY_MESSAGES:]
            if item.get("role") in {"user", "assistant"} and isinstance(item.get("content"), str)
        ],
        "summary": summary[:MAX_CONTEXT_LENGTH],
        "chapters": chapters,
        "sources": [
            {"id": number, "start": source.start, "end": source.end, "text": source.text}
            for number, source in enumerate(sources, 1)
        ],
    }
    result = await llm.complete(PROMPT, json.dumps(context, ensure_ascii=False), json_mode=True)
    return parse_reply(result, sources)
