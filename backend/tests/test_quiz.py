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
    NotificationKind,
    NotificationOutcome,
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
from tests.conftest import notifications


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


SEGMENTS = [
    TranscriptSegment(start=i * 10.0, end=i * 10.0 + 9, text=f"фраза {i}") for i in range(10)
]
VALID = answer([make_question(n) for n in range(8)])


def test_parse_questions_accepts_valid_answer():
    questions = parse_questions("```json\n" + VALID + "\n```", SEGMENTS, lecture_end=100)

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
def test_parse_questions_drops_broken_question(broken):
    questions = [make_question(n) for n in range(8)]
    questions[3] = broken

    parsed = parse_questions(answer(questions), SEGMENTS, lecture_end=100)

    assert [q["question"] for q in parsed] == [f"Вопрос {n}" for n in range(8) if n != 3]


def test_parse_questions_rejects_too_few_valid_questions():
    questions = [make_question(n) for n in range(8)]
    questions[0:3] = [make_question(correct_index=9)] * 3

    with pytest.raises(InvalidQuiz, match="5 корректных вопросов"):
        parse_questions(answer(questions), SEGMENTS, lecture_end=100)


@pytest.mark.parametrize(("size", "expected"), [(6, 6), (12, 12), (14, 12)])
def test_parse_questions_limits_question_count(size, expected):
    parsed = parse_questions(
        answer([make_question(n) for n in range(size)]), SEGMENTS, lecture_end=1000
    )

    assert len(parsed) == expected


def test_parse_questions_rejects_five_questions():
    with pytest.raises(InvalidQuiz):
        parse_questions(answer([make_question(n) for n in range(5)]), SEGMENTS, lecture_end=1000)


def test_parse_questions_rejects_non_json():
    with pytest.raises(ValueError):
        parse_questions("Вот ваш квиз", SEGMENTS, lecture_end=100)


def test_long_transcript_is_cut_evenly():
    segments = [
        TranscriptSegment(start=m * 60.0, end=m * 60.0 + 59, text="слово " * 20) for m in range(240)
    ]

    excerpt = transcript_excerpt(segments, limit=8000)

    assert len(excerpt) <= 8000 + 100
    assert "[0] " in excerpt
    assert "[13500] " in excerpt
    assert "[840] " in excerpt
    assert "[14340] " in excerpt


LECTURE = [
    (0.0, "Здравствуйте, сегодня говорим о производной."),
    (
        42.5,
        "Производная функции в точке — это предел отношения приращения функции "
        "к приращению аргумента.",
    ),
    (75.0, "Теперь про интегралы: интеграл — это площадь под графиком."),
    (130.0, "Ещё раз напомню, что производная характеризует скорость изменения функции."),
]


def lecture_segments(lines=LECTURE) -> list[TranscriptSegment]:
    return [TranscriptSegment(start=start, end=start + 10, text=text) for start, text in lines]


def evidence_answer(*items: dict) -> str:
    return answer([make_question(n, **items[n % len(items)]) for n in range(8)])


def test_evidence_quote_sets_timestamp():
    content = evidence_answer(
        {"evidence": "предел отношения приращения функции к приращению аргумента", "timestamp": 0}
    )

    questions = parse_questions(content, lecture_segments(), lecture_end=200)

    assert {q["timestamp"] for q in questions} == {42.5}


def test_evidence_quote_with_differences_sets_timestamp():
    content = evidence_answer(
        {
            "evidence": "Производная — это предел отношения приращений функции и аргумента",
            "timestamp": 0,
        }
    )

    questions = parse_questions(content, lecture_segments(), lecture_end=200)

    assert {q["timestamp"] for q in questions} == {42.5}


def test_evidence_ignores_case_punctuation_and_yo():
    segments = lecture_segments([(5.0, "Ёлка, ПОЛНЫЙ порядок: всё будет «хорошо»!")])

    content = evidence_answer({"evidence": "елка полный  порядок все будет хорошо", "timestamp": 0})

    assert {q["timestamp"] for q in parse_questions(content, segments, lecture_end=20)} == {5.0}


def test_evidence_across_two_replies_points_to_first():
    segments = lecture_segments(
        [(10.0, "Интеграл есть"), (20.0, "площадь под графиком"), (30.0, "всё")]
    )

    content = evidence_answer({"evidence": "интеграл есть площадь под графиком", "timestamp": 30})

    assert {q["timestamp"] for q in parse_questions(content, segments, lecture_end=50)} == {10.0}


def test_repeated_quote_uses_model_timestamp_as_tiebreak():
    segments = lecture_segments(
        [(0.0, "вступление"), (60.0, "Запомните это правило."), (900.0, "Запомните это правило.")]
    )

    content = evidence_answer({"evidence": "Запомните это правило", "timestamp": 905})

    assert {q["timestamp"] for q in parse_questions(content, segments, lecture_end=1000)} == {900.0}


def test_multi_part_lecture_finds_quote_in_later_part():
    segments = lecture_segments(
        [(0.0, "Вводная часть про организацию курса.")]
        + [(float(m * 60), f"Минута {m} посвящена другому материалу.") for m in range(1, 40)]
        + [(2400.0, "Матрица называется вырожденной, если её определитель равен нулю.")]
    )

    content = evidence_answer(
        {
            "evidence": "матрица называется вырожденной если её определитель равен нулю",
            "timestamp": 0,
        }
    )

    assert {q["timestamp"] for q in parse_questions(content, segments, lecture_end=2500)} == {
        2400.0
    }


def test_missing_quote_falls_back_to_word_overlap():
    items = {
        "question": "Что характеризует производная?",
        "explanation": "Производная характеризует скорость изменения функции.",
        "evidence": "",
        "timestamp": 0,
    }

    questions = parse_questions(evidence_answer(items), lecture_segments(), lecture_end=200)

    assert {q["timestamp"] for q in questions} == {130.0}


def test_unrelated_quote_falls_back_to_word_overlap():
    items = {
        "question": "Чему равен интеграл?",
        "explanation": "Интеграл — это площадь под графиком.",
        "evidence": "цитата которой нет в лекции вообще",
        "timestamp": 10,
    }

    questions = parse_questions(evidence_answer(items), lecture_segments(), lecture_end=200)

    assert {q["timestamp"] for q in questions} == {75.0}


def test_model_timestamp_is_snapped_to_reply_start():
    items = {"question": "Вопрос", "explanation": "Нет совпадений", "evidence": "", "timestamp": 80}

    questions = parse_questions(evidence_answer(items), lecture_segments(), lecture_end=200)

    assert {q["timestamp"] for q in questions} == {75.0}


def test_zero_timestamp_rejected_when_reply_does_not_start_at_zero():
    segments = lecture_segments([(12.0, "Первая реплика"), (50.0, "Вторая реплика")])
    items = {"question": "Вопрос", "explanation": "Нет совпадений", "evidence": "", "timestamp": 0}

    with pytest.raises(InvalidQuiz):
        parse_questions(evidence_answer(items), segments, lecture_end=100)


def test_zero_timestamp_accepted_when_first_reply_starts_at_zero():
    items = {"question": "Вопрос", "explanation": "Нет совпадений", "evidence": "", "timestamp": 0}

    questions = parse_questions(evidence_answer(items), lecture_segments(), lecture_end=200)

    assert {q["timestamp"] for q in questions} == {0.0}


def test_no_quote_and_no_timestamp_is_rejected():
    items = {
        "question": "Вопрос",
        "explanation": "Нет совпадений",
        "evidence": "",
        "timestamp": None,
    }

    with pytest.raises(InvalidQuiz):
        parse_questions(evidence_answer(items), lecture_segments(), lecture_end=200)


class ScriptedLLM:
    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.requests: list[str] = []

    async def complete(self, system: str, user: str, *, json_mode: bool = False, max_tokens: int | None = None) -> str:
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
    assert await notifications(lecture.id) == [(NotificationKind.quiz, NotificationOutcome.ready)]


async def test_quiz_fails_after_three_invalid_answers(user, monkeypatch):
    llm = ScriptedLLM("{}", "{}", "{}", VALID)
    monkeypatch.setattr(quiz, "get_llm", lambda: llm)
    lecture = await create_ready_lecture(user)

    assert await tasks.process_quiz({}, str(lecture.id)) == StepStatus.failed

    assert len(llm.requests) == 3
    step = await quiz_step(lecture.id)
    assert step.status == StepStatus.failed
    assert "в ответе нет списка вопросов" in step.error
    assert await saved_quiz(lecture.id) is None
    async with SessionLocal() as session:
        assert (await session.get(Lecture, lecture.id)).status == LectureStatus.ready
    assert await notifications(lecture.id) == [(NotificationKind.quiz, NotificationOutcome.failed)]


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
