import asyncio

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select, update

from app.api import lectures as lectures_api
from app.core.db import SessionLocal
from app.models import (
    Chapter,
    Lecture,
    LectureStatus,
    NotificationKind,
    NotificationOutcome,
    ProcessingStep,
    SearchChunk,
    SourceType,
    StepName,
    StepStatus,
    Summary,
    TranscriptSegment,
    User,
)
from app.pipeline import summarize, tasks
from app.pipeline.runner import STEP_ERRORS
from tests.conftest import notifications
from tests.test_summarize import FailingReduceLLM, ScriptedLLM


async def create_lecture(owner: User, status=LectureStatus.ready, **fields) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=owner.id,
            title="Матанализ",
            source_type=SourceType.upload,
            status=status,
            duration_sec=1800,
            **fields,
        )
        session.add(lecture)
        await session.flush()
        session.add_all(
            TranscriptSegment(
                lecture_id=lecture.id,
                idx=i,
                start=i * 60.0,
                end=i * 60.0 + 59,
                text=f"фраза {i}",
            )
            for i in range(30)
        )
        session.add(Chapter(lecture_id=lecture.id, idx=0, start=0, end=1800, title="Старая глава"))
        session.add(Summary(lecture_id=lecture.id, content_md="Старый конспект"))
        session.add_all(
            ProcessingStep(
                lecture_id=lecture.id,
                step=name,
                status=StepStatus.done,
                progress=1.0,
                attempts=1,
            )
            for name in (StepName.transcribe, StepName.summarize, StepName.embed)
        )
        await session.commit()
        return lecture


async def steps_of(lecture_id) -> dict[StepName, ProcessingStep]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(ProcessingStep).where(ProcessingStep.lecture_id == lecture_id)
        )
        return {row.step: row for row in rows}


async def lecture_status(lecture_id) -> LectureStatus:
    async with SessionLocal() as session:
        return (await session.get(Lecture, lecture_id)).status


async def stored_texts(lecture_id) -> tuple[list[str], str, int]:
    async with SessionLocal() as session:
        titles = await session.scalars(
            select(Chapter.title).where(Chapter.lecture_id == lecture_id).order_by(Chapter.idx)
        )
        content = await session.scalar(
            select(Summary.content_md).where(Summary.lecture_id == lecture_id)
        )
        segments = await session.scalar(
            select(func.count()).where(TranscriptSegment.lecture_id == lecture_id)
        )
        return list(titles), content, segments


@pytest.fixture
def queue(monkeypatch):
    state = {"enqueued": []}

    async def fake_enqueue(lecture_id):
        state["enqueued"].append(lecture_id)

    monkeypatch.setattr(lectures_api, "enqueue_regeneration", fake_enqueue)
    return state


def url(lecture) -> str:
    return f"/api/v1/lectures/{lecture.id}/regenerate-summary"


async def test_regenerate_replaces_chapters_and_keeps_transcript(
    client, user, auth_headers, queue, monkeypatch
):
    monkeypatch.setattr(summarize, "get_llm", ScriptedLLM)
    lecture = await create_lecture(user)

    response = await client.post(url(lecture), headers=auth_headers)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "processing"
    assert queue["enqueued"] == [lecture.id]
    pending = {step["step"]: step["status"] for step in body["steps"]}
    assert pending["summarize"] == pending["embed"] == "pending"
    assert pending["transcribe"] == "done"

    assert await tasks.process_regeneration({}, str(lecture.id)) == StepStatus.done

    titles, content, segments = await stored_texts(lecture.id)
    assert "Старая глава" not in titles
    assert titles
    assert content.startswith("## Глава 1")
    assert segments == 30
    assert await lecture_status(lecture.id) == LectureStatus.ready
    steps = await steps_of(lecture.id)
    assert steps[StepName.summarize].status == StepStatus.done
    assert steps[StepName.embed].status == StepStatus.done
    assert steps[StepName.transcribe].attempts == 1
    assert await notifications(lecture.id) == [
        (NotificationKind.regenerate, NotificationOutcome.ready)
    ]
    async with SessionLocal() as session:
        chunks = await session.scalar(
            select(func.count()).where(SearchChunk.lecture_id == lecture.id)
        )
    assert chunks > 0


async def test_failed_generation_keeps_previous_content(
    client, user, auth_headers, queue, monkeypatch
):
    monkeypatch.setattr(summarize, "get_llm", FailingReduceLLM)
    lecture = await create_lecture(user)
    await client.post(url(lecture), headers=auth_headers)

    assert await tasks.process_regeneration({}, str(lecture.id)) == StepStatus.failed

    titles, content, segments = await stored_texts(lecture.id)
    assert titles == ["Старая глава"]
    assert content == "Старый конспект"
    assert segments == 30
    assert await lecture_status(lecture.id) == LectureStatus.ready
    steps = await steps_of(lecture.id)
    assert steps[StepName.summarize].status == StepStatus.failed
    assert steps[StepName.summarize].error == "Сервис конспектов недоступен, попробуйте позже"
    assert steps[StepName.embed].status == StepStatus.done
    assert await notifications(lecture.id) == [
        (NotificationKind.regenerate, NotificationOutcome.failed)
    ]


async def test_other_user_gets_404(client, user, auth_headers, queue):
    async with SessionLocal() as session:
        stranger = User(display_name="Чужой")
        session.add(stranger)
        await session.commit()
    lecture = await create_lecture(stranger)
    try:
        response = await client.post(url(lecture), headers=auth_headers)
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, stranger.id))
            await session.commit()

    assert response.status_code == 404
    assert queue["enqueued"] == []


@pytest.mark.parametrize(
    "status", [LectureStatus.processing, LectureStatus.queued, LectureStatus.failed]
)
async def test_not_ready_lecture_gets_409(client, user, auth_headers, queue, status):
    lecture = await create_lecture(user, status=status)

    response = await client.post(url(lecture), headers=auth_headers)

    assert response.status_code == 409
    assert queue["enqueued"] == []


async def test_second_request_during_processing_gets_409(client, user, auth_headers, queue):
    lecture = await create_lecture(user)
    await client.post(url(lecture), headers=auth_headers)

    response = await client.post(url(lecture), headers=auth_headers)

    assert response.status_code == 409
    assert queue["enqueued"] == [lecture.id]


async def test_locally_processed_lecture_gets_409(client, user, auth_headers, queue):
    lecture = await create_lecture(user, processed_locally=True)

    response = await client.post(url(lecture), headers=auth_headers)

    assert response.status_code == 409
    assert queue["enqueued"] == []


async def test_missing_ai_consent_gets_403(client, user, auth_headers, queue):
    async with SessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(ai_transfer_accepted_at=None, ai_transfer_revision=None)
        )
        await session.commit()
    lecture = await create_lecture(user)

    response = await client.post(url(lecture), headers=auth_headers)

    assert response.status_code == 403
    assert "согласия на передачу данных" in response.json()["detail"]
    assert queue["enqueued"] == []
    assert await lecture_status(lecture.id) == LectureStatus.ready


async def test_repeat_within_window_gets_429(client, user, auth_headers, queue, monkeypatch):
    monkeypatch.setattr(summarize, "get_llm", ScriptedLLM)
    lecture = await create_lecture(user)
    await client.post(url(lecture), headers=auth_headers)
    await tasks.process_regeneration({}, str(lecture.id))

    response = await client.post(url(lecture), headers=auth_headers)

    assert response.status_code == 429
    assert queue["enqueued"] == [lecture.id]
    assert await lecture_status(lecture.id) == LectureStatus.ready


async def test_queue_down_restores_ready_state(client, user, auth_headers, monkeypatch):
    async def queue_down(lecture_id):
        raise RedisConnectionError("нет связи")

    monkeypatch.setattr(lectures_api, "enqueue_regeneration", queue_down)
    lecture = await create_lecture(user)

    response = await client.post(url(lecture), headers=auth_headers)

    assert response.status_code == 503
    assert await lecture_status(lecture.id) == LectureStatus.ready
    assert await notifications(lecture.id) == []
    steps = await steps_of(lecture.id)
    assert steps[StepName.summarize].status == StepStatus.done

    async def accepted(lecture_id):
        return None

    monkeypatch.setattr(lectures_api, "enqueue_regeneration", accepted)
    retry = await client.post(url(lecture), headers=auth_headers)
    assert retry.status_code == 202


async def test_unexpected_error_restores_ready_state(
    client, user, auth_headers, queue, monkeypatch
):
    class Aborted(BaseException):
        pass

    async def aborting_step(
        session, lecture, name, handler, *, fails_lecture=True, defer_scope=None
    ):
        raise Aborted

    lecture = await create_lecture(user)
    await client.post(url(lecture), headers=auth_headers)
    monkeypatch.setattr(tasks, "run_step", aborting_step)

    with pytest.raises(Aborted):
        await tasks.process_regeneration({}, str(lecture.id))

    assert await lecture_status(lecture.id) == LectureStatus.ready
    titles, content, _ = await stored_texts(lecture.id)
    assert titles == ["Старая глава"]
    assert content == "Старый конспект"
    steps = await steps_of(lecture.id)
    assert steps[StepName.summarize].status == StepStatus.done
    assert await notifications(lecture.id) == [
        (NotificationKind.regenerate, NotificationOutcome.failed)
    ]


async def test_cancelled_regeneration_is_redone_on_retry(
    client, user, auth_headers, queue, monkeypatch
):
    monkeypatch.setattr(summarize, "get_llm", ScriptedLLM)
    lecture = await create_lecture(user)
    await client.post(url(lecture), headers=auth_headers)
    calls = []
    summarize_step = tasks.HANDLERS[StepName.summarize]
    embed_step = tasks.HANDLERS[StepName.embed]

    async def tracked_summarize(session, lecture, report):
        calls.append(StepName.summarize)
        await summarize_step(session, lecture, report)

    async def cancelled_once(session, lecture, report):
        calls.append(StepName.embed)
        if calls.count(StepName.embed) == 1:
            raise asyncio.CancelledError
        await embed_step(session, lecture, report)

    monkeypatch.setitem(tasks.HANDLERS, StepName.summarize, tracked_summarize)
    monkeypatch.setitem(tasks.HANDLERS, StepName.embed, cancelled_once)

    with pytest.raises(asyncio.CancelledError):
        await tasks.process_regeneration({}, str(lecture.id))

    assert await lecture_status(lecture.id) == LectureStatus.processing
    steps = await steps_of(lecture.id)
    assert steps[StepName.embed].status != StepStatus.done
    assert await notifications(lecture.id) == []

    assert await tasks.process_regeneration({}, str(lecture.id)) == StepStatus.done

    assert calls == [StepName.summarize, StepName.embed, StepName.summarize, StepName.embed]
    assert await lecture_status(lecture.id) == LectureStatus.ready
    steps = await steps_of(lecture.id)
    assert steps[StepName.summarize].status == StepStatus.done
    assert steps[StepName.embed].status == StepStatus.done
    assert steps[StepName.embed].attempts == 3


async def test_embed_failure_is_reported_in_ready_event(
    client, user, auth_headers, queue, monkeypatch
):
    monkeypatch.setattr(summarize, "get_llm", ScriptedLLM)
    lecture = await create_lecture(user)
    await client.post(url(lecture), headers=auth_headers)
    published = []

    async def broken_embed(session, lecture, report):
        raise RuntimeError("эмбеддинги недоступны")

    async def record(lecture_id, user_id, status, error=None):
        published.append((status, error))

    monkeypatch.setitem(tasks.HANDLERS, StepName.embed, broken_embed)
    monkeypatch.setattr(tasks, "publish_status", record)

    assert await tasks.process_regeneration({}, str(lecture.id)) == StepStatus.failed

    assert published == [(LectureStatus.ready, STEP_ERRORS[StepName.embed])]
    steps = await steps_of(lecture.id)
    assert steps[StepName.summarize].status == StepStatus.done
    assert steps[StepName.embed].status == StepStatus.failed


async def test_timed_out_regeneration_restores_ready_state(
    client, user, auth_headers, queue, monkeypatch
):
    monkeypatch.setattr(summarize, "get_llm", ScriptedLLM)
    lecture = await create_lecture(user)
    await client.post(url(lecture), headers=auth_headers)

    async def endless(session, lecture, report):
        await asyncio.sleep(60)

    monkeypatch.setattr(tasks, "REGENERATION_TIMEOUT_SEC", 0.5)
    monkeypatch.setitem(tasks.HANDLERS, StepName.embed, endless)

    with pytest.raises(TimeoutError):
        await tasks.process_regeneration({}, str(lecture.id))

    assert await lecture_status(lecture.id) == LectureStatus.ready
    steps = await steps_of(lecture.id)
    assert steps[StepName.embed].status == StepStatus.failed
    assert await notifications(lecture.id) == [
        (NotificationKind.regenerate, NotificationOutcome.failed)
    ]
