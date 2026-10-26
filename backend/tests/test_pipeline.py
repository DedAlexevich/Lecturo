import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api import lectures as lectures_api
from app.core.db import SessionLocal
from app.models import (
    Chapter,
    Lecture,
    LectureStatus,
    SearchChunk,
    SourceType,
    StepName,
    StepStatus,
    Summary,
    TranscriptSegment,
)
from app.pipeline import tasks
from app.pipeline.stages import split_into_chunks


async def create_lecture(user) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title="Матанализ", source_type=SourceType.upload)
        session.add(lecture)
        await session.commit()
        return lecture


async def load(lecture_id) -> Lecture:
    async with SessionLocal() as session:
        return await session.scalar(
            select(Lecture).where(Lecture.id == lecture_id).options(selectinload(Lecture.steps))
        )


async def count(model, lecture_id) -> int:
    async with SessionLocal() as session:
        return await session.scalar(
            select(func.count()).select_from(model).where(model.lecture_id == lecture_id)
        )


def steps_by_name(lecture: Lecture) -> dict:
    return {step.step: step for step in lecture.steps}


async def test_lecture_passes_all_steps(user):
    lecture = await create_lecture(user)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    lecture = await load(lecture.id)
    assert lecture.status == LectureStatus.ready
    assert lecture.duration_sec
    steps = steps_by_name(lecture)
    assert set(steps) == {StepName.transcribe, StepName.summarize, StepName.embed}
    assert all(s.status == StepStatus.done and s.progress == 1.0 for s in steps.values())
    assert await count(TranscriptSegment, lecture.id) > 0
    assert await count(Chapter, lecture.id) == 1
    assert await count(Summary, lecture.id) == 1
    assert await count(SearchChunk, lecture.id) > 0


async def test_failed_step_retries_without_repeating_done_steps(
    user, client, auth_headers, monkeypatch
):
    lecture = await create_lecture(user)
    calls = {"summarize": 0}
    original = tasks.HANDLERS[StepName.summarize]

    async def flaky_summarize(session, lecture, report):
        calls["summarize"] += 1
        if calls["summarize"] == 1:
            raise RuntimeError("LLM недоступна")
        await original(session, lecture, report)

    monkeypatch.setitem(tasks.HANDLERS, StepName.summarize, flaky_summarize)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.failed
    failed = await load(lecture.id)
    steps = steps_by_name(failed)
    assert failed.status == LectureStatus.failed
    assert steps[StepName.transcribe].status == StepStatus.done
    assert steps[StepName.summarize].status == StepStatus.failed
    assert steps[StepName.summarize].error == "LLM недоступна"
    assert StepName.embed not in steps

    enqueued = []

    async def fake_enqueue(lecture_id):
        enqueued.append(lecture_id)

    monkeypatch.setattr(lectures_api, "enqueue_lecture", fake_enqueue)
    response = await client.post(f"/api/v1/lectures/{lecture.id}/retry", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert enqueued == [lecture.id]

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    steps = steps_by_name(await load(lecture.id))
    assert steps[StepName.transcribe].attempts == 1
    assert steps[StepName.summarize].attempts == 2
    assert all(s.status == StepStatus.done for s in steps.values())


async def test_retry_rejects_lecture_that_did_not_fail(user, client, auth_headers):
    lecture = await create_lecture(user)
    response = await client.post(f"/api/v1/lectures/{lecture.id}/retry", headers=auth_headers)
    assert response.status_code == 409


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        ([(0, 20), (20, 40), (40, 59)], [(0, 59)]),
        ([(0, 30), (30, 61), (61, 90)], [(0, 30), (30, 90)]),
        ([], []),
    ],
)
def test_split_into_chunks(bounds, expected):
    segments = [TranscriptSegment(start=s, end=e, text="т") for s, e in bounds]
    assert [(s, e) for s, e, _ in split_into_chunks(segments)] == expected


async def test_error_outside_step_marks_lecture_failed(user, monkeypatch):
    lecture = await create_lecture(user)

    async def broken_get_step(*args):
        raise ConnectionError("база недоступна")

    monkeypatch.setattr("app.pipeline.runner.get_step", broken_get_step)

    with pytest.raises(ConnectionError):
        await tasks.process_lecture({}, str(lecture.id))
    assert (await load(lecture.id)).status == LectureStatus.failed


async def test_cancelled_job_marks_running_step_failed(user, monkeypatch):
    lecture = await create_lecture(user)

    async def cancelled(session, lecture, report):
        raise asyncio.CancelledError

    monkeypatch.setitem(tasks.HANDLERS, StepName.transcribe, cancelled)

    with pytest.raises(asyncio.CancelledError):
        await tasks.process_lecture({}, str(lecture.id))
    failed = await load(lecture.id)
    assert failed.status == LectureStatus.failed
    assert steps_by_name(failed)[StepName.transcribe].status == StepStatus.failed


async def fail_lecture(user) -> Lecture:
    lecture = await create_lecture(user)

    async def broken(session, lecture, report):
        raise RuntimeError("сбой")

    original = tasks.HANDLERS[StepName.transcribe]
    tasks.HANDLERS[StepName.transcribe] = broken
    try:
        await tasks.process_lecture({}, str(lecture.id))
    finally:
        tasks.HANDLERS[StepName.transcribe] = original
    return lecture


async def test_retry_returns_lecture_to_failed_when_queue_is_down(
    user, client, auth_headers, monkeypatch
):
    lecture = await fail_lecture(user)

    async def queue_down(lecture_id):
        raise ConnectionRefusedError

    monkeypatch.setattr(lectures_api, "enqueue_lecture", queue_down)
    response = await client.post(f"/api/v1/lectures/{lecture.id}/retry", headers=auth_headers)
    assert response.status_code == 503
    assert (await load(lecture.id)).status == LectureStatus.failed


async def test_second_retry_is_rejected(user, client, auth_headers, monkeypatch):
    lecture = await fail_lecture(user)

    async def fake_enqueue(lecture_id):
        pass

    monkeypatch.setattr(lectures_api, "enqueue_lecture", fake_enqueue)
    url = f"/api/v1/lectures/{lecture.id}/retry"
    first = await client.post(url, headers=auth_headers)
    second = await client.post(url, headers=auth_headers)
    assert first.status_code == 200
    assert second.status_code == 409


async def test_link_lecture_downloads_audio_before_transcribe(user, monkeypatch):
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Лекция по ссылке",
            source_type=SourceType.link,
            source_url="https://vkvideo.ru/video-1_2",
        )
        session.add(lecture)
        await session.commit()
    order = []

    async def fake_download(session, lecture, report):
        order.append(StepName.download)
        lecture.audio_path = f"/data/storage/audio/{lecture.id}.opus"

    original = tasks.HANDLERS[StepName.transcribe]

    async def tracked_transcribe(session, lecture, report):
        order.append(StepName.transcribe)
        await original(session, lecture, report)

    monkeypatch.setitem(tasks.HANDLERS, StepName.download, fake_download)
    monkeypatch.setitem(tasks.HANDLERS, StepName.transcribe, tracked_transcribe)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    loaded = await load(lecture.id)
    assert order == [StepName.download, StepName.transcribe]
    assert loaded.audio_path == f"/data/storage/audio/{lecture.id}.opus"
    assert steps_by_name(loaded)[StepName.download].status == StepStatus.done
