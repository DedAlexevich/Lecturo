import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.models import (
    Lecture,
    LectureStatus,
    ProcessingStep,
    SourceType,
    StepName,
    StepStatus,
    TranscriptSegment,
    User,
)
from app.pipeline import dedup_segments, tasks

PHRASES = [(0.0, 4.0, "раз"), (4.0, 8.0, "два"), (8.0, 12.0, "три")]


async def create_lecture(user, phrases, status=LectureStatus.ready, **fields) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Матанализ",
            source_type=fields.pop("source_type", SourceType.link),
            status=status,
            **fields,
        )
        session.add(lecture)
        await session.flush()
        session.add_all(
            TranscriptSegment(lecture_id=lecture.id, idx=idx, start=start, end=end, text=text)
            for idx, (start, end, text) in enumerate(phrases)
        )
        session.add_all(
            ProcessingStep(
                lecture_id=lecture.id, step=name, status=StepStatus.done, progress=1.0, attempts=1
            )
            for name in (StepName.transcribe, StepName.summarize, StepName.embed)
        )
        await session.commit()
        return lecture


def doubled(phrases):
    return [phrase for phrase in phrases for _ in range(2)]


async def segments_of(lecture_id) -> list[tuple[int, float, float, str]]:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(
                TranscriptSegment.idx,
                TranscriptSegment.start,
                TranscriptSegment.end,
                TranscriptSegment.text,
            )
            .where(TranscriptSegment.lecture_id == lecture_id)
            .order_by(TranscriptSegment.idx)
        )
        return [tuple(row) for row in rows]


async def state_of(lecture_id) -> tuple[LectureStatus, dict[StepName, StepStatus]]:
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, lecture_id)
        steps = await session.scalars(
            select(ProcessingStep).where(ProcessingStep.lecture_id == lecture_id)
        )
        return lecture.status, {step.step: step.status for step in steps}


@pytest.fixture
def enqueued(monkeypatch) -> list:
    calls = []

    async def fake_enqueue(lecture_id):
        calls.append(lecture_id)

    async def no_publish(*args):
        pass

    monkeypatch.setattr(dedup_segments, "enqueue_regeneration", fake_enqueue)
    monkeypatch.setattr(dedup_segments, "publish_status", no_publish)
    return calls


async def test_duplicates_are_removed_and_lecture_regenerated(user, enqueued):
    affected = await create_lecture(user, doubled(PHRASES))
    clean = await create_lecture(user, PHRASES)

    result = await dedup_segments.dedup_segments()

    assert (result.lectures, result.segments) == (1, 3)
    assert result.regenerated == [affected.id]
    assert enqueued == [affected.id]
    expected = [(idx, *phrase) for idx, phrase in enumerate(PHRASES)]
    assert await segments_of(affected.id) == expected
    assert await segments_of(clean.id) == expected
    status, steps = await state_of(affected.id)
    assert status == LectureStatus.processing
    assert steps == {
        StepName.transcribe: StepStatus.done,
        StepName.summarize: StepStatus.pending,
        StepName.embed: StepStatus.pending,
    }
    assert await state_of(clean.id) == (
        LectureStatus.ready,
        {name: StepStatus.done for name in steps},
    )

    assert await tasks.process_regeneration({}, str(affected.id)) == StepStatus.done
    assert (await state_of(affected.id))[0] == LectureStatus.ready


async def test_second_run_changes_nothing(user, enqueued):
    lecture = await create_lecture(user, doubled(PHRASES))
    await dedup_segments.dedup_segments()

    result = await dedup_segments.dedup_segments()

    assert (result.lectures, result.segments, result.regenerated) == (0, 0, [])
    assert result.not_queued == []
    assert enqueued == [lecture.id]


async def test_close_but_different_segments_are_kept(user, enqueued):
    phrases = [(0.0, 4.0, "раз"), (0.0, 4.0, "раз."), (0.5, 4.0, "раз")]
    lecture = await create_lecture(user, phrases)

    result = await dedup_segments.dedup_segments()

    assert result.lectures == 0
    assert len(await segments_of(lecture.id)) == 3


@pytest.mark.parametrize(
    "fields",
    [
        {"status": LectureStatus.failed},
        {"status": LectureStatus.ready, "processed_locally": True},
        {"status": LectureStatus.ready, "source_type": SourceType.local},
    ],
    ids=["not-ready", "processed-locally", "local-source"],
)
async def test_only_server_ready_lectures_are_regenerated(user, enqueued, fields):
    lecture = await create_lecture(user, doubled(PHRASES), **fields)

    result = await dedup_segments.dedup_segments()

    assert (result.lectures, result.regenerated, result.skipped) == (1, [], [lecture.id])
    assert enqueued == []
    assert len(await segments_of(lecture.id)) == 3
    status, steps = await state_of(lecture.id)
    assert status == fields["status"]
    assert steps[StepName.summarize] == StepStatus.done


async def test_owner_without_consent_is_not_regenerated(user, enqueued):
    async with SessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(ai_transfer_accepted_at=None, ai_transfer_revision=None)
        )
        await session.commit()
    lecture = await create_lecture(user, doubled(PHRASES))

    result = await dedup_segments.dedup_segments()

    assert (result.regenerated, result.skipped) == ([], [lecture.id])
    assert enqueued == []
    assert len(await segments_of(lecture.id)) == 3
    assert (await state_of(lecture.id))[0] == LectureStatus.ready


async def test_queue_error_restores_lecture_and_continues(user, enqueued, monkeypatch):
    first = await create_lecture(user, doubled(PHRASES))
    second = await create_lecture(user, doubled(PHRASES))
    failing, queued = sorted([first.id, second.id])

    async def flaky_enqueue(lecture_id):
        if lecture_id == failing:
            raise RedisConnectionError("нет связи")
        enqueued.append(lecture_id)

    monkeypatch.setattr(dedup_segments, "enqueue_regeneration", flaky_enqueue)

    result = await dedup_segments.dedup_segments()

    assert result.not_queued == [failing]
    assert result.regenerated == [queued]
    assert enqueued == [queued]
    status, steps = await state_of(failing)
    assert status == LectureStatus.ready
    assert steps[StepName.summarize] == steps[StepName.embed] == StepStatus.done
    assert (await state_of(queued))[0] == LectureStatus.processing
    assert len(await segments_of(failing)) == 3
