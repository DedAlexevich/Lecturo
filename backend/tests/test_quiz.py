import json
from datetime import UTC, datetime, timedelta

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select, update

from app.api import lectures as lectures_api
from app.core.db import SessionLocal
from app.models import (
    Lecture,
    LectureStatus,
    ProcessingStep,
    Quiz,
    SourceType,
    StepName,
    StepStatus,
    Subscription,
    TranscriptSegment,
    User,
)
from app.pipeline import quiz, tasks
from app.pipeline.quiz import InvalidQuiz, parse_questions, transcript_excerpt


def make_question(number: int = 0, **changes) -> dict:
    question = {
        "question": f"Вопрос {number}",
        "options": ["А", "Б", "В", "Г"],
        "correct_index": number % 4,
        "explanation": "Так сказал лектор.",
        "timestamp": number * 10,
    }
    return question | changes


def answer(questions: list[dict]) -> str:
    return json.dumps({"questions": questions}, ensure_ascii=False)


VALID = answer([make_question(n) for n in range(8)])


def test_parse_questions_accepts_valid_answer():
    questions = parse_questions("```json\n" + VALID + "\n```", lecture_end=100)

    assert len(questions) == 8
    assert questions[1] == {
        "question": "Вопрос 1",
        "options": ["А", "Б", "В", "Г"],
        "correct_index": 1,
        "explanation": "Так сказал лектор.",
        "timestamp": 10.0,
    }


@pytest.mark.parametrize(
    "broken",
    [
        make_question(correct_index=4),
        make_question(correct_index=-1),
        make_question(correct_index=True),
        make_question(correct_index="1"),
        make_question(timestamp=101),
        make_question(timestamp=-5),
        make_question(timestamp=None),
        make_question(question=" "),
        make_question(options=["А"]),
        make_question(options=["А", "А", "Б"]),
        "не вопрос",
    ],
)
def test_parse_questions_rejects_broken_question(broken):
    questions = [make_question(n) for n in range(8)]
    questions[3] = broken

    with pytest.raises(InvalidQuiz):
        parse_questions(answer(questions), lecture_end=100)


@pytest.mark.parametrize("size", [7, 13])
def test_parse_questions_checks_question_count(size):
    with pytest.raises(InvalidQuiz):
        parse_questions(answer([make_question(n) for n in range(size)]), lecture_end=1000)


def test_parse_questions_rejects_non_json():
    with pytest.raises(ValueError):
        parse_questions("Вот ваш квиз", lecture_end=100)


def test_long_transcript_is_cut_evenly():
    segments = [
        TranscriptSegment(start=m * 60.0, end=m * 60.0 + 59, text="слово " * 20) for m in range(240)
    ]

    excerpt = transcript_excerpt(segments, limit=8000)

    assert len(excerpt) <= 8000 + 100
    assert "[0] " in excerpt
    assert "[13500] " in excerpt


class ScriptedLLM:
    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.requests: list[str] = []

    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        assert json_mode
        assert system == quiz.load_prompt("quiz")
        self.requests.append(user)
        return self.answers.pop(0)


async def create_ready_lecture(owner: User, status=LectureStatus.ready) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=owner.id,
            title="Матанализ",
            source_type=SourceType.upload,
            status=status,
            duration_sec=100,
        )
        session.add(lecture)
        await session.flush()
        session.add_all(
            TranscriptSegment(
                lecture_id=lecture.id, idx=i, start=i * 10.0, end=i * 10.0 + 9, text=f"фраза {i}"
            )
            for i in range(10)
        )
        await session.commit()
        return lecture


async def quiz_step(lecture_id) -> ProcessingStep | None:
    async with SessionLocal() as session:
        return await session.scalar(
            select(ProcessingStep).where(
                ProcessingStep.lecture_id == lecture_id, ProcessingStep.step == StepName.quiz
            )
        )


async def saved_quiz(lecture_id) -> Quiz | None:
    async with SessionLocal() as session:
        return await session.scalar(select(Quiz).where(Quiz.lecture_id == lecture_id))


async def test_invalid_answers_are_regenerated_twice(user, monkeypatch):
    broken = answer([make_question(n, timestamp=500) for n in range(8)])
    llm = ScriptedLLM("не JSON", broken, VALID)
    monkeypatch.setattr(quiz, "get_llm", lambda: llm)
    lecture = await create_ready_lecture(user)

    assert await tasks.process_quiz({}, str(lecture.id)) == StepStatus.done

    assert len(llm.requests) == 3
    request = json.loads(llm.requests[0])
    assert request["title"] == "Матанализ"
    assert "[90] фраза 9" in request["transcript"]
    assert len((await saved_quiz(lecture.id)).questions) == 8
    assert (await quiz_step(lecture.id)).status == StepStatus.done


async def test_quiz_fails_after_three_invalid_answers(user, monkeypatch):
    llm = ScriptedLLM("{}", "{}", "{}", VALID)
    monkeypatch.setattr(quiz, "get_llm", lambda: llm)
    lecture = await create_ready_lecture(user)

    assert await tasks.process_quiz({}, str(lecture.id)) == StepStatus.failed

    assert len(llm.requests) == 3
    step = await quiz_step(lecture.id)
    assert step.status == StepStatus.failed
    assert "от 8 до 12 вопросов" in step.error
    assert await saved_quiz(lecture.id) is None
    async with SessionLocal() as session:
        assert (await session.get(Lecture, lecture.id)).status == LectureStatus.ready


async def test_quiz_on_stub_llm_replaces_previous(user):
    lecture = await create_ready_lecture(user)

    await tasks.process_quiz({}, str(lecture.id))
    first = await saved_quiz(lecture.id)
    async with SessionLocal() as session:
        await session.execute(
            update(ProcessingStep)
            .where(ProcessingStep.lecture_id == lecture.id)
            .values(status=StepStatus.pending)
        )
        await session.commit()
    await tasks.process_quiz({}, str(lecture.id))

    second = await saved_quiz(lecture.id)
    assert second.id == first.id
    assert len(second.questions) == 8
    assert all(0 <= q["timestamp"] <= 100 for q in second.questions)


@pytest.fixture
async def subscriber(user):
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        session.add(
            Subscription(
                user_id=user.id, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=29)
            )
        )
        await session.commit()
    return user


@pytest.fixture
def queue(monkeypatch):
    state = {"enqueued": [], "active": False}

    async def fake_enqueue(lecture_id):
        state["enqueued"].append(lecture_id)

    async def fake_active(lecture_id):
        return state["active"]

    monkeypatch.setattr(lectures_api, "enqueue_quiz", fake_enqueue)
    monkeypatch.setattr(lectures_api, "quiz_job_active", fake_active)
    return state


async def test_create_and_get_quiz(client, subscriber, auth_headers, queue):
    lecture = await create_ready_lecture(subscriber)
    url = f"/api/v1/lectures/{lecture.id}/quiz"

    missing = await client.get(url, headers=auth_headers)
    created = await client.post(url, headers=auth_headers)

    assert missing.status_code == 404
    assert created.status_code == 202
    assert queue["enqueued"] == [lecture.id]
    assert (await quiz_step(lecture.id)).status == StepStatus.pending

    await tasks.process_quiz({}, str(lecture.id))
    response = await client.get(url, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["lecture_id"] == str(lecture.id)
    assert len(body["questions"]) == 8
    assert set(body["questions"][0]) == {
        "question",
        "options",
        "correct_index",
        "explanation",
        "timestamp",
    }


async def test_create_quiz_does_not_duplicate_active_job(client, subscriber, auth_headers, queue):
    lecture = await create_ready_lecture(subscriber)
    url = f"/api/v1/lectures/{lecture.id}/quiz"
    await client.post(url, headers=auth_headers)
    queue["active"] = True

    response = await client.post(url, headers=auth_headers)

    assert response.status_code == 202
    assert queue["enqueued"] == [lecture.id]


async def test_create_quiz_restarts_stale_step(client, subscriber, auth_headers, queue):
    lecture = await create_ready_lecture(subscriber)
    url = f"/api/v1/lectures/{lecture.id}/quiz"
    await client.post(url, headers=auth_headers)

    response = await client.post(url, headers=auth_headers)

    assert response.status_code == 202
    assert queue["enqueued"] == [lecture.id, lecture.id]


async def test_quiz_needs_processed_lecture(client, subscriber, auth_headers, queue):
    lecture = await create_ready_lecture(subscriber, status=LectureStatus.processing)

    response = await client.post(f"/api/v1/lectures/{lecture.id}/quiz", headers=auth_headers)

    assert response.status_code == 409
    assert queue["enqueued"] == []


async def test_quiz_of_other_user_is_hidden(client, subscriber, auth_headers, queue):
    async with SessionLocal() as session:
        stranger = User(display_name="Чужой")
        session.add(stranger)
        await session.commit()
    lecture = await create_ready_lecture(stranger)
    url = f"/api/v1/lectures/{lecture.id}/quiz"
    try:
        created = await client.post(url, headers=auth_headers)
        fetched = await client.get(url, headers=auth_headers)
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, stranger.id))
            await session.commit()

    assert created.status_code == 404
    assert fetched.status_code == 404
    assert queue["enqueued"] == []


async def test_create_quiz_reports_queue_down(client, subscriber, auth_headers, monkeypatch):
    async def queue_down(lecture_id):
        raise RedisConnectionError("нет связи")

    monkeypatch.setattr(lectures_api, "enqueue_quiz", queue_down)
    lecture = await create_ready_lecture(subscriber)

    response = await client.post(f"/api/v1/lectures/{lecture.id}/quiz", headers=auth_headers)

    assert response.status_code == 503
    step = await quiz_step(lecture.id)
    assert step.status == StepStatus.failed
    assert step.error == lectures_api.QUEUE_UNAVAILABLE
