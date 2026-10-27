import json
import uuid
from datetime import UTC, datetime, timedelta

from app.core.db import SessionLocal
from app.models import Chapter, Lecture, LectureStatus, SourceType, Subscription, Summary
from app.schemas.search import SearchHit


class ChatLLM:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def complete(self, system, user, *, json_mode=False):
        self.requests.append((system, json.loads(user), json_mode))
        return self.response


async def create_lecture(user, status=LectureStatus.ready):
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Пределы",
            source_type=SourceType.upload,
            status=status,
            chapters=[Chapter(idx=0, start=10, end=20, title="Предел", summary="Определение")],
            summary=Summary(content_md="Конспект"),
        )
        session.add(lecture)
        await session.commit()
        return lecture.id


async def add_subscription(user):
    async with SessionLocal() as session:
        now = datetime.now(UTC)
        session.add(Subscription(user_id=user.id, starts_at=now, ends_at=now + timedelta(days=30)))
        await session.commit()


async def test_chat_returns_verified_timestamps_for_owned_lecture(
    client, user, auth_headers, monkeypatch
):
    lecture_id = await create_lecture(user)
    await add_subscription(user)
    hit = SearchHit(
        lecture_id=lecture_id,
        lecture_title="Пределы",
        kind="transcript",
        start=10,
        end=20,
        section=0,
        text="Предел равен двум",
        score=0.5,
    )
    llm = ChatLLM(
        json.dumps(
            {
                "related": True,
                "lecture_answer": "Предел равен двум.",
                "additional": "Предел описывает поведение функции.",
                "source_ids": [1],
            }
        )
    )

    rate_limits = []

    async def allow_rate_limit(*args):
        rate_limits.append(args)
        return None

    async def no_embedding(question):
        return None

    async def search(session, scope, question, vector):
        return [hit]

    monkeypatch.setattr("app.api.lecture_chat.enforce_rate_limit", allow_rate_limit)
    monkeypatch.setattr("app.api.lecture_chat.embed_query", no_embedding)
    monkeypatch.setattr("app.api.lecture_chat.semantic_search", search)
    monkeypatch.setattr("app.api.lecture_chat.get_llm", lambda: llm)

    response = await client.post(
        f"/api/v1/lectures/{lecture_id}/chat",
        json={"question": "  Чему равен предел?  ", "history": []},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "answered",
        "answer": "Предел равен двум.",
        "extra": "Предел описывает поведение функции.",
        "sources": [{"kind": "transcript", "start": 10, "end": 20, "text": "Предел равен двум"}],
    }
    assert llm.requests[0][1]["question"] == "Чему равен предел?"
    assert llm.requests[0][1]["summary"] == "Конспект"
    assert llm.requests[0][1]["chapters"] == [{"title": "Предел", "summary": "Определение"}]
    assert rate_limits[0][2:] == (40, 60)


async def test_chat_rejects_missing_and_unready_lecture(client, user, auth_headers):
    lecture_id = await create_lecture(user, LectureStatus.processing)
    response = await client.post(
        f"/api/v1/lectures/{lecture_id}/chat", json={"question": "Вопрос"}, headers=auth_headers
    )
    assert response.status_code == 409

    missing = await client.post(
        f"/api/v1/lectures/{uuid.uuid4()}/chat",
        json={"question": "Вопрос"},
        headers=auth_headers,
    )
    assert missing.status_code == 404


async def test_chat_requires_subscription(client, user, auth_headers):
    lecture_id = await create_lecture(user)
    response = await client.post(
        f"/api/v1/lectures/{lecture_id}/chat", json={"question": "Вопрос"}, headers=auth_headers
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "subscription_required"


async def test_chat_without_timed_sources_does_not_call_model(
    client, user, auth_headers, monkeypatch
):
    lecture_id = await create_lecture(user)
    await add_subscription(user)
    llm = ChatLLM("{}")

    async def allow_rate_limit(*args):
        return None

    async def no_embedding(question):
        return None

    async def no_sources(session, scope, question, vector):
        return []

    monkeypatch.setattr("app.api.lecture_chat.enforce_rate_limit", allow_rate_limit)
    monkeypatch.setattr("app.api.lecture_chat.embed_query", no_embedding)
    monkeypatch.setattr("app.api.lecture_chat.semantic_search", no_sources)
    monkeypatch.setattr("app.api.lecture_chat.get_llm", lambda: llm)

    response = await client.post(
        f"/api/v1/lectures/{lecture_id}/chat",
        json={"question": "Вопрос"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_found"
    assert not llm.requests


async def test_chat_validates_question_and_history(client, user, auth_headers):
    lecture_id = await create_lecture(user)
    too_many_messages = [{"role": "user", "content": "Вопрос"}] * 11
    long_question = "x" * 1001

    too_many = await client.post(
        f"/api/v1/lectures/{lecture_id}/chat",
        json={"question": "Вопрос", "history": too_many_messages},
        headers=auth_headers,
    )
    too_long = await client.post(
        f"/api/v1/lectures/{lecture_id}/chat",
        json={"question": long_question},
        headers=auth_headers,
    )

    assert too_many.status_code == 422
    assert too_long.status_code == 422
