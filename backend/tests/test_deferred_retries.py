import pytest
from arq import Retry
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import (
    Lecture,
    LectureStatus,
    NotificationKind,
    NotificationOutcome,
    ProcessingStep,
    SourceType,
    StepName,
    StepStatus,
    TranscriptSegment,
)
from app.pipeline import exam, quiz, summarize, tasks
from app.pipeline.runner import STEP_ERRORS
from app.pipeline.summarize import load_prompt
from app.providers.openai_compat import OpenAICompatibleError, OpenAICompatibleUnavailable
from tests import test_exam_sheet, test_quiz
from tests.conftest import notifications
from tests.test_exam_sheet import create_course
from tests.test_summarize import ScriptedLLM

DELAYS = [60, 300, 900]
LATE_TRY = {"job_try": 40}


@pytest.fixture(autouse=True)
def defer_delays(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_retry_defer_seconds", DELAYS)


@pytest.fixture(autouse=True)
def no_video_job(monkeypatch):
    async def skip(lecture_id) -> None:
        return None

    monkeypatch.setattr(tasks, "enqueue_video", skip)


class FlakyLLM(ScriptedLLM):
    def __init__(self, outages: int, error: Exception | None = None) -> None:
        super().__init__()
        self.outages = outages
        self.error = error or OpenAICompatibleUnavailable("/chat/completions: API ответил 500")
        self.map_calls = 0

    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if "фрагмент расшифровки" in system:
            self.map_calls += 1
        elif self.outages:
            self.outages -= 1
            raise self.error
        return await super().complete(system, user, json_mode=json_mode)


async def transcribed_lecture(user) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Матанализ",
            source_type=SourceType.upload,
            status=LectureStatus.queued,
            duration_sec=3600,
        )
        session.add(lecture)
        await session.flush()
        session.add_all(
            TranscriptSegment(
                lecture_id=lecture.id, idx=i, start=i * 60.0, end=i * 60.0 + 59, text=f"фраза {i}"
            )
            for i in range(60)
        )
        session.add_all(
            ProcessingStep(
                lecture_id=lecture.id, step=name, status=StepStatus.done, progress=1.0, attempts=1
            )
            for name in (StepName.audio, StepName.transcribe)
        )
        await session.commit()
        return lecture


async def state(lecture_id) -> tuple[LectureStatus, dict[StepName, ProcessingStep]]:
    async with SessionLocal() as session:
        status = (await session.get(Lecture, lecture_id)).status
        rows = await session.scalars(
            select(ProcessingStep).where(ProcessingStep.lecture_id == lecture_id)
        )
        return status, {row.step: row for row in rows}


async def exhaust(run) -> None:
    for _ in DELAYS:
        with pytest.raises(Retry):
            await run()


@pytest.fixture
def refunds(monkeypatch) -> list:
    calls = []
    original = tasks.refund

    async def tracked(lecture_id) -> None:
        calls.append(lecture_id)
        await original(lecture_id)

    monkeypatch.setattr(tasks, "refund", tracked)
    return calls


async def test_transient_llm_error_defers_lecture_and_second_try_succeeds(
    user, monkeypatch, refunds
):
    llm = FlakyLLM(outages=1)
    monkeypatch.setattr(summarize, "get_llm", lambda: llm)
    lecture = await transcribed_lecture(user)

    with pytest.raises(Retry) as deferred:
        await tasks.process_lecture(LATE_TRY, str(lecture.id))

    assert deferred.value.defer_score == DELAYS[0] * 1000
    status, steps = await state(lecture.id)
    assert status == LectureStatus.processing
    assert steps[StepName.summarize].status == StepStatus.pending
    assert steps[StepName.summarize].error is None
    assert StepName.embed not in steps
    assert await notifications(lecture.id) == []
    assert refunds == []
    map_calls = llm.map_calls

    assert await tasks.process_lecture(LATE_TRY, str(lecture.id)) == LectureStatus.ready

    assert llm.map_calls == map_calls
    status, steps = await state(lecture.id)
    assert status == LectureStatus.ready
    assert steps[StepName.transcribe].attempts == 1
    assert steps[StepName.summarize].attempts == 2
    assert steps[StepName.embed].status == StepStatus.done
    assert refunds == []
    assert await notifications(lecture.id) == [
        (NotificationKind.lecture, NotificationOutcome.ready)
    ]


async def test_deferral_delay_grows_regardless_of_job_try(user, monkeypatch):
    monkeypatch.setattr(summarize, "get_llm", lambda: FlakyLLM(outages=10))
    lecture = await transcribed_lecture(user)

    scores = []
    for _ in DELAYS:
        with pytest.raises(Retry) as deferred:
            await tasks.process_lecture(LATE_TRY, str(lecture.id))
        scores.append(deferred.value.defer_score)

    assert scores == [delay * 1000 for delay in DELAYS]


async def test_exhausted_deferrals_fail_lecture_with_clear_error(user, monkeypatch, refunds):
    monkeypatch.setattr(summarize, "get_llm", lambda: FlakyLLM(outages=10))
    lecture = await transcribed_lecture(user)

    await exhaust(lambda: tasks.process_lecture(LATE_TRY, str(lecture.id)))
    assert await tasks.process_lecture(LATE_TRY, str(lecture.id)) == LectureStatus.failed

    status, steps = await state(lecture.id)
    assert status == LectureStatus.failed
    assert steps[StepName.summarize].status == StepStatus.failed
    assert steps[StepName.summarize].error == STEP_ERRORS[StepName.summarize]
    assert "500" not in steps[StepName.summarize].error
    assert refunds == [lecture.id]


async def test_permanent_llm_error_fails_lecture_at_once(user, monkeypatch):
    error = OpenAICompatibleError("/chat/completions: API ответил 400: bad request")
    monkeypatch.setattr(summarize, "get_llm", lambda: FlakyLLM(outages=1, error=error))
    lecture = await transcribed_lecture(user)

    assert await tasks.process_lecture(LATE_TRY, str(lecture.id)) == LectureStatus.failed

    status, steps = await state(lecture.id)
    assert status == LectureStatus.failed
    assert steps[StepName.summarize].error == STEP_ERRORS[StepName.summarize]


async def test_regeneration_is_deferred_on_transient_error(user, monkeypatch):
    llm = FlakyLLM(outages=0)
    monkeypatch.setattr(summarize, "get_llm", lambda: llm)
    lecture = await transcribed_lecture(user)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    llm.outages = 1
    async with SessionLocal() as session:
        stored = await session.get(Lecture, lecture.id)
        stored.status = LectureStatus.processing
        await session.commit()

    with pytest.raises(Retry):
        await tasks.process_regeneration(LATE_TRY, str(lecture.id))

    status, steps = await state(lecture.id)
    assert status == LectureStatus.processing
    assert steps[StepName.summarize].status == StepStatus.pending

    assert await tasks.process_regeneration(LATE_TRY, str(lecture.id)) == StepStatus.done
    status, _ = await state(lecture.id)
    assert status == LectureStatus.ready


class FlakyQuizLLM(test_quiz.ScriptedLLM):
    def __init__(self, outages: int, error: Exception | None = None) -> None:
        super().__init__(test_quiz.VALID)
        self.outages = outages
        self.error = error or OpenAICompatibleUnavailable("/chat/completions: нет ответа от API")

    async def complete(
        self, system: str, user: str, *, json_mode: bool = False, max_tokens: int | None = None
    ) -> str:
        if self.outages:
            self.outages -= 1
            raise self.error
        return await super().complete(system, user, json_mode=json_mode, max_tokens=max_tokens)


async def test_quiz_is_deferred_and_built_on_next_try(user, monkeypatch):
    llm = FlakyQuizLLM(outages=1)
    monkeypatch.setattr(quiz, "get_llm", lambda: llm)
    lecture = await test_quiz.create_ready_lecture(user)

    with pytest.raises(Retry) as deferred:
        await tasks.process_quiz(LATE_TRY, str(lecture.id))

    assert deferred.value.defer_score == DELAYS[0] * 1000
    step = await test_quiz.quiz_step(lecture.id)
    assert step.status == StepStatus.pending
    assert step.error is None
    assert await notifications(lecture.id) == []

    assert await tasks.process_quiz(LATE_TRY, str(lecture.id)) == StepStatus.done
    assert (await test_quiz.quiz_step(lecture.id)).status == StepStatus.done
    assert await notifications(lecture.id) == [(NotificationKind.quiz, NotificationOutcome.ready)]


async def test_quiz_fails_after_last_deferral(user, monkeypatch):
    monkeypatch.setattr(quiz, "get_llm", lambda: FlakyQuizLLM(outages=10))
    lecture = await test_quiz.create_ready_lecture(user)

    await exhaust(lambda: tasks.process_quiz(LATE_TRY, str(lecture.id)))
    assert await tasks.process_quiz(LATE_TRY, str(lecture.id)) == StepStatus.failed

    step = await test_quiz.quiz_step(lecture.id)
    assert step.status == StepStatus.failed
    assert step.error == STEP_ERRORS[StepName.quiz]
    assert await notifications(lecture.id) == [(NotificationKind.quiz, NotificationOutcome.failed)]


async def test_quiz_permanent_error_fails_at_once(user, monkeypatch):
    error = OpenAICompatibleError("/chat/completions: API ответил 401: unauthorized")
    monkeypatch.setattr(quiz, "get_llm", lambda: FlakyQuizLLM(outages=100, error=error))
    lecture = await test_quiz.create_ready_lecture(user)

    assert await tasks.process_quiz(LATE_TRY, str(lecture.id)) == StepStatus.failed
    assert (await test_quiz.quiz_step(lecture.id)).error.startswith("Не удалось собрать квиз")


class UnavailableLLM:
    async def complete(
        self, system: str, user: str, *, json_mode: bool = False, max_tokens: int | None = None
    ) -> str:
        raise OpenAICompatibleUnavailable("/chat/completions: API ответил 503 после 4 попыток")


async def test_exam_sheet_is_deferred_then_marked_failed(user, monkeypatch):
    monkeypatch.setattr(exam, "get_llm", UnavailableLLM)
    course_id = await create_course(user)

    await exhaust(lambda: exam.build_exam_sheet(LATE_TRY, str(course_id)))
    assert not await exam.exam_sheet_failed(course_id)

    with pytest.raises(OpenAICompatibleUnavailable):
        await exam.build_exam_sheet(LATE_TRY, str(course_id))
    assert await exam.exam_sheet_failed(course_id)
    await exam.clear_exam_sheet_failure(course_id)


class FlakyExamLLM(test_exam_sheet.ScriptedLLM):
    def __init__(self) -> None:
        super().__init__()
        self.outages = 1

    async def complete(
        self, system: str, user: str, *, json_mode: bool = False, max_tokens: int | None = None
    ) -> str:
        if system == load_prompt("exam_reduce") and self.outages:
            self.outages -= 1
            raise OpenAICompatibleUnavailable("/chat/completions: API ответил 429 после 4 попыток")
        return await super().complete(system, user, json_mode=json_mode)


async def test_exam_sheet_reuses_lecture_digests_after_deferral(user, monkeypatch):
    llm = FlakyExamLLM()
    monkeypatch.setattr(exam, "get_llm", lambda: llm)
    course_id = await create_course(user)

    with pytest.raises(Retry):
        await exam.build_exam_sheet(LATE_TRY, str(course_id))
    assert len(llm.map_requests) == len(test_exam_sheet.LECTURES)

    assert await exam.build_exam_sheet(LATE_TRY, str(course_id)) == "ready"
    assert len(llm.map_requests) == len(test_exam_sheet.LECTURES)
    assert len(llm.reduce_requests) == 1
