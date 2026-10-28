import json
import uuid

import pytest

from app.models import ChunkKind
from app.schemas.search import SearchHit
from app.services.lecture_chat import (
    MAX_CONTEXT_LENGTH,
    InvalidChatReply,
    answer_question,
    limit_notes,
    parse_reply,
    select_sources,
)


class ScriptedLLM:
    def __init__(self, response):
        self.response = json.dumps(response, ensure_ascii=False)
        self.requests = []

    async def complete(self, system, user, *, json_mode=False):
        assert json_mode
        self.requests.append((system, json.loads(user)))
        return self.response


def hit(lecture_id, text="Предел равен двум", start=10, end=15, kind=ChunkKind.transcript):
    return SearchHit(
        lecture_id=lecture_id,
        lecture_title="Пределы",
        kind=kind,
        start=start,
        end=end,
        section=None,
        text=text,
        description=None,
        chapter_title=None,
        score=0.5,
    )


async def test_answer_uses_only_owned_lecture_sources():
    lecture_id = uuid.uuid4()
    llm = ScriptedLLM(
        {
            "related": True,
            "lecture_answer": "Предел равен двум.",
            "additional": "Предел описывает поведение функции.",
            "source_ids": [1, 1],
        }
    )
    reply = await answer_question(
        llm,
        lecture_id=lecture_id,
        title="Пределы",
        question="Чему равен предел?",
        history=[{"role": "user", "content": "Что такое предел?"}],
        summary="Конспект лекции",
        chapters=[{"title": "Предел", "summary": "Определение"}],
        hits=[hit(uuid.uuid4(), "Чужой фрагмент"), hit(lecture_id)],
    )
    assert reply.status == "answered"
    assert reply.answer == "Предел равен двум."
    assert reply.extra == "Предел описывает поведение функции."
    assert [(source.start, source.end) for source in reply.sources] == [(10, 15)]
    sent = llm.requests[0][1]
    assert len(sent["sources"]) == 1
    assert sent["sources"][0]["text"] == "Предел равен двум"
    assert "Чужой фрагмент" not in json.dumps(sent, ensure_ascii=False)


async def test_no_sources_does_not_call_model():
    llm = ScriptedLLM({})
    reply = await answer_question(
        llm,
        lecture_id=uuid.uuid4(),
        title="Лекция",
        question="Вопрос",
        history=[],
        summary="",
        chapters=[],
        hits=[],
    )
    assert not llm.requests
    assert reply.status == "not_found"
    assert not reply.sources
    assert "не найден" in reply.answer


def test_unrelated_question_never_returns_generated_text_or_sources():
    sources = select_sources(uuid.UUID(int=1), [hit(uuid.UUID(int=1))])
    reply = parse_reply(
        json.dumps(
            {
                "related": False,
                "lecture_answer": "лишний ответ",
                "additional": "лишнее",
                "source_ids": [1],
            }
        ),
        sources,
    )
    assert reply.status == "off_topic"
    assert "не относится" in reply.answer
    assert reply.extra is None
    assert not reply.sources


@pytest.mark.parametrize("ids", [[], [0], [2], [True], ["1"]])
def test_lecture_answer_requires_real_source_ids(ids):
    sources = select_sources(uuid.UUID(int=1), [hit(uuid.UUID(int=1))])
    with pytest.raises(InvalidChatReply):
        parse_reply(
            json.dumps(
                {"related": True, "lecture_answer": "Ответ", "additional": "", "source_ids": ids}
            ),
            sources,
        )


def test_sources_with_invalid_timestamps_are_discarded():
    lecture_id = uuid.uuid4()
    hits = [
        hit(lecture_id, start=float("nan")),
        hit(lecture_id, start=-1),
        hit(lecture_id, start=12, end=11),
        hit(lecture_id, text="  "),
        hit(lecture_id, start=1, end=2),
    ]
    assert [source.start for source in select_sources(lecture_id, hits)] == [1]


def test_only_timestamped_transcript_and_chapter_sources_are_selected():
    lecture_id = uuid.uuid4()
    hits = [
        hit(lecture_id, "Конспект", start=None, end=None, kind=ChunkKind.summary),
        hit(lecture_id, "Фрагмент без времени", start=None, end=None),
        hit(lecture_id, "Глава", start=20, end=30, kind=ChunkKind.chapter),
    ]
    assert [source.text for source in select_sources(lecture_id, hits)] == ["Глава"]


def test_summary_and_chapters_share_a_bounded_context():
    summary, chapters = limit_notes("Конспект", [{"title": "Глава", "summary": "x" * 20000}])

    assert summary == "Конспект"
    assert (
        len(summary) + sum(len(chapter["title"]) + len(chapter["summary"]) for chapter in chapters)
        == MAX_CONTEXT_LENGTH
    )
