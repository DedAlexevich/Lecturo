import asyncio

import pytest
from redis.exceptions import RedisError
from sqlalchemy import func, select

from app.api import billing as billing_api
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import (
    HourPackage,
    Lecture,
    LectureStatus,
    ProcessingStep,
    SourceType,
    StepName,
    StepStatus,
    UsageEntry,
    User,
)
from app.pipeline import tasks
from app.services import quota

HOUR = 3600


@pytest.fixture
def weekly_limit(monkeypatch) -> int:
    monkeypatch.setattr(get_settings(), "free_weekly_seconds", 2 * HOUR)
    return 2 * HOUR


@pytest.fixture
def handlers(monkeypatch) -> list:
    calls = []

    async def done(session, lecture, report):
        calls.append(lecture.id)

    for name in StepName:
        if name != StepName.transcribe:
            monkeypatch.setitem(tasks.HANDLERS, name, done)
    return calls


@pytest.fixture
def published(monkeypatch) -> list:
    events = []

    async def fake_publish(lecture_id, user_id, status, error=None):
        events.append((lecture_id, status))

    monkeypatch.setattr(billing_api, "publish_status", fake_publish)
    return events


@pytest.fixture
def enqueued(monkeypatch) -> list:
    calls = []

    async def fake_enqueue(lecture_id):
        calls.append(lecture_id)

    monkeypatch.setattr(billing_api, "enqueue_lecture", fake_enqueue)
    return calls


async def new_lecture(
    user, seconds: float | None, status=LectureStatus.queued, title="Лекция"
) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title=title,
            source_type=SourceType.upload,
            duration_sec=seconds,
            status=status,
        )
        session.add(lecture)
        await session.commit()
        return lecture


async def status_of(lecture) -> LectureStatus:
    async with SessionLocal() as session:
        return await session.scalar(select(Lecture.status).where(Lecture.id == lecture.id))


async def charged(lecture) -> int:
    async with SessionLocal() as session:
        return await session.scalar(
            select(func.coalesce(func.sum(UsageEntry.seconds), 0)).where(
                UsageEntry.lecture_id == lecture.id
            )
        )


async def test_can_process_compares_with_available(user, weekly_limit):
    async with SessionLocal() as session:
        db_user = await session.get(User, user.id)
        assert await quota.can_process(session, db_user, weekly_limit)
        assert not await quota.can_process(session, db_user, weekly_limit + 0.5)


async def test_worker_charges_lecture_that_fits(user, weekly_limit, handlers):
    lecture = await new_lecture(user, HOUR)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    assert await charged(lecture) == HOUR


async def test_lecture_over_limit_waits_without_processing(user, weekly_limit, handlers):
    first = await new_lecture(user, 1.5 * HOUR)
    second = await new_lecture(user, HOUR)

    assert await tasks.process_lecture({}, str(first.id)) == LectureStatus.ready
    assert await tasks.process_lecture({}, str(second.id)) == LectureStatus.waiting_quota

    assert await status_of(second) == LectureStatus.waiting_quota
    assert await charged(second) == 0
    async with SessionLocal() as session:
        steps = dict(
            (
                await session.execute(
                    select(ProcessingStep.step, ProcessingStep.status).where(
                        ProcessingStep.lecture_id == second.id
                    )
                )
            ).all()
        )
    assert steps[StepName.transcribe] == StepStatus.pending
    async with SessionLocal() as session:
        step = await session.scalar(
            select(ProcessingStep).where(
                ProcessingStep.lecture_id == second.id,
                ProcessingStep.step == StepName.transcribe,
            )
        )
    assert step.attempts == 0
    assert step.progress == 0.0
    assert step.started_at is None
    assert StepName.summarize not in steps


async def planned_lecture(user, client, auth_headers, seconds=HOUR) -> Lecture:
    lecture = await new_lecture(user, seconds, LectureStatus.waiting_quota)
    response = await client.post(
        "/api/v1/billing/queue-plan", json={"lecture_ids": [str(lecture.id)]}, headers=auth_headers
    )
    assert response.status_code == 200
    return lecture


async def test_failure_before_transcribe_returns_quota(
    user, auth_headers, client, weekly_limit, handlers, enqueued, published, monkeypatch
):
    lecture = await planned_lecture(user, client, auth_headers)
    assert await charged(lecture) == HOUR

    async def broken(session, lecture, report):
        raise RuntimeError("ffmpeg упал")

    monkeypatch.setitem(tasks.HANDLERS, StepName.audio, broken)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.failed
    assert await charged(lecture) == 0


async def test_cancel_before_transcribe_returns_quota(
    user, auth_headers, client, weekly_limit, handlers, enqueued, published, monkeypatch
):
    lecture = await planned_lecture(user, client, auth_headers)

    async def cancelled(session, lecture, report):
        raise asyncio.CancelledError

    monkeypatch.setitem(tasks.HANDLERS, StepName.audio, cancelled)

    with pytest.raises(asyncio.CancelledError):
        await tasks.process_lecture({}, str(lecture.id))
    assert await status_of(lecture) == LectureStatus.failed
    assert await charged(lecture) == 0


async def test_failure_after_transcribe_keeps_single_charge_on_retry(
    user, weekly_limit, handlers, monkeypatch
):
    lecture = await new_lecture(user, HOUR)
    original = tasks.HANDLERS[StepName.summarize]

    async def broken(session, lecture, report):
        raise RuntimeError("модель недоступна")

    monkeypatch.setitem(tasks.HANDLERS, StepName.summarize, broken)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.failed
    assert await charged(lecture) == HOUR

    monkeypatch.setitem(tasks.HANDLERS, StepName.summarize, original)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    assert await charged(lecture) == HOUR


async def test_cancel_after_transcribe_keeps_charge(user, weekly_limit, handlers, monkeypatch):
    lecture = await new_lecture(user, HOUR)

    async def cancelled(session, lecture, report):
        raise asyncio.CancelledError

    monkeypatch.setitem(tasks.HANDLERS, StepName.summarize, cancelled)

    with pytest.raises(asyncio.CancelledError):
        await tasks.process_lecture({}, str(lecture.id))
    assert await status_of(lecture) == LectureStatus.failed
    assert await charged(lecture) == HOUR


async def test_ready_lecture_keeps_charge_after_late_error(user, weekly_limit, handlers):
    lecture = await new_lecture(user, HOUR)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    await tasks.mark_failed(lecture.id, "поздняя ошибка")

    assert await status_of(lecture) == LectureStatus.ready
    assert await charged(lecture) == HOUR


async def test_local_lecture_is_not_charged(user, weekly_limit, handlers):
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="На устройстве",
            source_type=SourceType.local,
            duration_sec=10 * HOUR,
        )
        session.add(lecture)
        await session.commit()

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    assert await charged(lecture) == 0


async def test_waiting_lists_lectures_and_remainder(user, auth_headers, client, weekly_limit):
    await new_lecture(user, HOUR, LectureStatus.ready)
    first = await new_lecture(user, 3 * HOUR, LectureStatus.waiting_quota, "Первая")
    second = await new_lecture(user, 1800, LectureStatus.waiting_quota, "Вторая")

    response = await client.get("/api/v1/billing/waiting", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["lectures"]] == [str(first.id), str(second.id)]
    assert body["lectures"][0] == {"id": str(first.id), "title": "Первая", "duration_sec": 3 * HOUR}
    assert body["available_sec"] == weekly_limit
    assert body["resets_at"]


async def test_queue_plan_runs_selected_in_given_order(
    user, auth_headers, client, weekly_limit, enqueued, published
):
    first = await new_lecture(user, HOUR, LectureStatus.waiting_quota)
    second = await new_lecture(user, 1800, LectureStatus.waiting_quota)
    left = await new_lecture(user, HOUR, LectureStatus.waiting_quota)

    response = await client.post(
        "/api/v1/billing/queue-plan",
        json={"lecture_ids": [str(second.id), str(first.id)]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert enqueued == [second.id, first.id]
    assert published == [(second.id, LectureStatus.queued), (first.id, LectureStatus.queued)]
    assert await status_of(first) == LectureStatus.queued
    assert await status_of(second) == LectureStatus.queued
    assert await charged(first) == HOUR
    assert await charged(second) == 1800
    body = response.json()
    assert [item["id"] for item in body["lectures"]] == [str(left.id)]
    assert body["available_sec"] == weekly_limit - HOUR - 1800


async def test_waiting_lecture_runs_after_plan_without_second_charge(
    user, auth_headers, client, weekly_limit, enqueued, handlers, published
):
    blocker = await new_lecture(user, 1.5 * HOUR)
    lecture = await new_lecture(user, HOUR)
    assert await tasks.process_lecture({}, str(blocker.id)) == LectureStatus.ready
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.waiting_quota
    async with SessionLocal() as session:
        session.add(HourPackage(user_id=user.id, seconds_total=HOUR, seconds_left=HOUR))
        await session.commit()

    await client.post(
        "/api/v1/billing/queue-plan", json={"lecture_ids": [str(lecture.id)]}, headers=auth_headers
    )

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    assert await charged(lecture) == HOUR


async def test_plan_over_remainder_is_rejected(user, auth_headers, client, weekly_limit, enqueued):
    first = await new_lecture(user, 1.5 * HOUR, LectureStatus.waiting_quota)
    second = await new_lecture(user, HOUR, LectureStatus.waiting_quota)

    response = await client.post(
        "/api/v1/billing/queue-plan",
        json={"lecture_ids": [str(first.id), str(second.id)]},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Выбранные лекции длятся 2 ч 30 мин, а осталось 2 ч. Уберите часть лекций из плана"
    )
    assert enqueued == []
    assert await status_of(first) == LectureStatus.waiting_quota
    assert await charged(first) == 0


async def test_plan_rejects_lecture_that_is_not_waiting(
    user, auth_headers, client, weekly_limit, enqueued
):
    waiting = await new_lecture(user, 60, LectureStatus.waiting_quota)
    ready = await new_lecture(user, 60, LectureStatus.ready)

    response = await client.post(
        "/api/v1/billing/queue-plan",
        json={"lecture_ids": [str(waiting.id), str(ready.id)]},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert enqueued == []
    assert await charged(waiting) == 0


async def test_plan_rejects_someone_elses_lecture(
    user, auth_headers, client, weekly_limit, enqueued
):
    async with SessionLocal() as session:
        stranger = User(display_name="Чужой")
        session.add(stranger)
        await session.commit()
    try:
        lecture = await new_lecture(stranger, 60, LectureStatus.waiting_quota)
        response = await client.post(
            "/api/v1/billing/queue-plan",
            json={"lecture_ids": [str(lecture.id)]},
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert await status_of(lecture) == LectureStatus.waiting_quota
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, stranger.id))
            await session.commit()


async def test_plan_rejects_repeated_lecture(user, auth_headers, client, weekly_limit, enqueued):
    lecture = await new_lecture(user, 60, LectureStatus.waiting_quota)

    response = await client.post(
        "/api/v1/billing/queue-plan",
        json={"lecture_ids": [str(lecture.id), str(lecture.id)]},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert enqueued == []


async def test_lecture_without_duration_is_charged_after_transcribe(
    user, auth_headers, client, weekly_limit, enqueued, handlers, published
):
    lecture = await new_lecture(user, None, LectureStatus.waiting_quota)

    response = await client.post(
        "/api/v1/billing/queue-plan", json={"lecture_ids": [str(lecture.id)]}, headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json()["available_sec"] == weekly_limit
    assert await status_of(lecture) == LectureStatus.queued
    assert await charged(lecture) == 0
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    assert await charged(lecture) == 60


async def test_waiting_shows_lecture_without_duration(user, auth_headers, client, weekly_limit):
    lecture = await new_lecture(user, None, LectureStatus.waiting_quota)

    response = await client.get("/api/v1/billing/waiting", headers=auth_headers)

    assert response.json()["lectures"] == [
        {"id": str(lecture.id), "title": "Лекция", "duration_sec": None}
    ]


async def test_plan_returns_lectures_to_waiting_when_queue_is_down(
    user, auth_headers, client, weekly_limit, monkeypatch, published
):
    first = await new_lecture(user, 60, LectureStatus.waiting_quota)
    second = await new_lecture(user, 60, LectureStatus.waiting_quota)
    enqueued = []

    async def flaky_enqueue(lecture_id):
        if enqueued:
            raise RedisError("нет связи")
        enqueued.append(lecture_id)

    monkeypatch.setattr(billing_api, "enqueue_lecture", flaky_enqueue)

    response = await client.post(
        "/api/v1/billing/queue-plan",
        json={"lecture_ids": [str(first.id), str(second.id)]},
        headers=auth_headers,
    )

    assert response.status_code == 503
    assert published[-1] == (second.id, LectureStatus.waiting_quota)
    assert await status_of(first) == LectureStatus.queued
    assert await charged(first) == 60
    assert await status_of(second) == LectureStatus.waiting_quota
    assert await charged(second) == 0


async def test_new_package_does_not_start_waiting_lectures(
    user, auth_headers, client, weekly_limit, enqueued
):
    lecture = await new_lecture(user, 3 * HOUR, LectureStatus.waiting_quota)
    async with SessionLocal() as session:
        session.add(HourPackage(user_id=user.id, seconds_total=5 * HOUR, seconds_left=5 * HOUR))
        await session.commit()

    response = await client.get("/api/v1/billing/waiting", headers=auth_headers)

    assert [item["id"] for item in response.json()["lectures"]] == [str(lecture.id)]
    assert response.json()["available_sec"] == weekly_limit + 5 * HOUR
    assert enqueued == []
    assert await status_of(lecture) == LectureStatus.waiting_quota
