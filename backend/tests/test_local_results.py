import pytest
from sqlalchemy import func, select

from app.api import local_results as local_results_api
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import (
    Chapter,
    Lecture,
    LectureStatus,
    SourceType,
    Summary,
    TranscriptSegment,
    UsageEntry,
    UsageSource,
)

TEXT = "слово " * 40
URL = "/api/v1/local-results"


def result_body(**overrides) -> dict:
    return {
        "title": "Матанализ",
        "duration_sec": 120.0,
        "model": "whisper-small",
        "segments": [
            {"start": 0.0, "end": 60.0, "text": TEXT},
            {"start": 60.0, "end": 120.0, "text": TEXT},
        ],
        "chapters": [{"start": 0.0, "end": 120.0, "title": "Введение", "summary": "Кратко"}],
        "summary_md": "# Конспект",
        **overrides,
    }


@pytest.fixture(autouse=True)
def queue(monkeypatch):
    enqueued = []

    async def fake_enqueue(lecture_id):
        enqueued.append(lecture_id)

    async def not_limited(*args):
        return False

    monkeypatch.setattr(local_results_api, "enqueue_lecture", fake_enqueue)
    monkeypatch.setattr(local_results_api, "is_rate_limited", not_limited)
    return enqueued


async def count(model, user_id) -> int:
    column = model.owner_id if model is Lecture else model.user_id
    async with SessionLocal() as session:
        return await session.scalar(
            select(func.count()).select_from(model).where(column == user_id)
        )


async def test_requires_auth(client):
    response = await client.post(URL, json=result_body())
    assert response.status_code == 401


async def test_saves_result_and_enqueues_embeddings(client, user, auth_headers, queue):
    response = await client.post(URL, json=result_body(), headers=auth_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["source_type"] == SourceType.local
    assert body["processed_locally"] is True
    assert body["status"] == LectureStatus.queued
    assert body["duration_sec"] == 120.0
    assert [str(item) for item in queue] == [body["id"]]

    async with SessionLocal() as session:
        lecture = await session.get(Lecture, queue[0])
        segments = await session.scalar(
            select(func.count())
            .select_from(TranscriptSegment)
            .where(TranscriptSegment.lecture_id == lecture.id)
        )
        chapters = await session.scalar(
            select(func.count()).select_from(Chapter).where(Chapter.lecture_id == lecture.id)
        )
        summary = await session.get(Summary, lecture.id)
        usage = await session.scalar(select(UsageEntry).where(UsageEntry.lecture_id == lecture.id))
    assert (segments, chapters) == (2, 1)
    assert summary.content_md == "# Конспект"
    assert usage.source == UsageSource.local_embeddings
    assert usage.seconds == 120


@pytest.mark.parametrize(
    "overrides",
    [
        {"segments": [{"start": 0.0, "end": 500.0, "text": TEXT}]},
        {
            "segments": [
                {"start": 60.0, "end": 100.0, "text": TEXT},
                {"start": 10.0, "end": 20.0, "text": TEXT},
            ]
        },
        {"segments": [{"start": 0.0, "end": 100.0, "text": "да"}]},
        {"chapters": [{"start": 0.0, "end": 500.0, "title": "Глава", "summary": ""}]},
    ],
)
async def test_implausible_result_rejected(client, user, auth_headers, overrides):
    response = await client.post(URL, json=result_body(**overrides), headers=auth_headers)

    assert response.status_code == 422
    assert await count(Lecture, user.id) == 0


async def test_weekly_duration_quota(client, user, auth_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "local_embeddings_weekly_seconds", 200)

    first = await client.post(URL, json=result_body(), headers=auth_headers)
    second = await client.post(URL, json=result_body(), headers=auth_headers)

    assert first.status_code == 201
    assert second.status_code == 429
    assert await count(Lecture, user.id) == 1


async def test_weekly_count_quota(client, user, auth_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "local_lectures_weekly_count", 1)

    first = await client.post(URL, json=result_body(), headers=auth_headers)
    second = await client.post(URL, json=result_body(), headers=auth_headers)

    assert (first.status_code, second.status_code) == (201, 429)


async def test_rate_limit(client, user, auth_headers, monkeypatch):
    async def limited(*args):
        return True

    monkeypatch.setattr(local_results_api, "is_rate_limited", limited)

    response = await client.post(URL, json=result_body(), headers=auth_headers)

    assert response.status_code == 429
    assert await count(Lecture, user.id) == 0


async def test_enqueue_failure_rolls_back(client, user, auth_headers, monkeypatch):
    async def broken(lecture_id):
        raise ConnectionError("redis недоступен")

    monkeypatch.setattr(local_results_api, "enqueue_lecture", broken)

    response = await client.post(URL, json=result_body(), headers=auth_headers)

    assert response.status_code == 503
    assert await count(Lecture, user.id) == 0
    assert await count(UsageEntry, user.id) == 0
