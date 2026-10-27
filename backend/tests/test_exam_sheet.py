import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import insert, select, update

from app.api import exam as exam_api
from app.core.db import SessionLocal
from app.models import (
    Course,
    ExamSheet,
    Lecture,
    SourceType,
    Subscription,
    Summary,
    User,
    course_lectures,
)
from app.pipeline import exam
from app.pipeline.summarize import load_prompt

LECTURES = [
    ("Пределы", "## Предел\n- Предел последовательности"),
    ("Производная", "## Производная\n- Производная функции"),
    ("Интеграл", "## Интеграл\n- Определённый интеграл"),
]


async def create_course(user, lectures=LECTURES) -> uuid.UUID:
    async with SessionLocal() as session:
        course = Course(owner_id=user.id, title="Матанализ")
        session.add(course)
        await session.flush()
        for position, (title, content) in enumerate(lectures):
            lecture = Lecture(owner_id=user.id, title=title, source_type=SourceType.upload)
            session.add(lecture)
            await session.flush()
            session.add(Summary(lecture_id=lecture.id, content_md=content))
            await session.execute(
                insert(course_lectures).values(
                    course_id=course.id, lecture_id=lecture.id, position=position
                )
            )
        await session.commit()
        return course.id


async def subscribe(user) -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        session.add(
            Subscription(
                user_id=user.id, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=29)
            )
        )
        await session.commit()


async def saved_sheet(course_id) -> dict | None:
    async with SessionLocal() as session:
        return await session.scalar(
            select(ExamSheet.content).where(ExamSheet.course_id == course_id)
        )


class ScriptedLLM:
    def __init__(self, reduce_answer: dict | None = None) -> None:
        self.reduce_answer = reduce_answer
        self.map_requests: list[str] = []
        self.reduce_requests: list[dict] = []

    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        assert json_mode
        if system == load_prompt("exam_map"):
            self.map_requests.append(user)
            title = user.splitlines()[0].removeprefix("# ")
            return json.dumps(
                {
                    "tickets": [f"Билет: {title}", "Общий вопрос"],
                    "definitions": [
                        {"term": title, "definition": f"Определение: {title}"},
                        {"term": "функция", "definition": f"Функция из лекции {title}"},
                    ],
                    "cheatsheet_md": f"- главное про {title}",
                }
            )
        self.reduce_requests.append(json.loads(user))
        return json.dumps(self.reduce_answer or {})


async def test_exam_sheet_for_three_lectures_on_stub_llm(user):
    course_id = await create_course(user)

    assert await exam.build_exam_sheet({}, str(course_id)) == "ready"

    content = await saved_sheet(course_id)
    assert set(content) == {"tickets", "definitions", "cheatsheet_md", "lecture_ids"}
    assert len(content["lecture_ids"]) == len(LECTURES)
    for title, _ in LECTURES:
        assert f"## {title}" in content["cheatsheet_md"]


async def test_exam_sheet_uses_reduce_answer(user, monkeypatch):
    answer = {
        "tickets": ["Билет 1", "Билет 2"],
        "definitions": [{"term": "Предел", "definition": "Число, к которому стремится"}],
        "cheatsheet_md": "## Курс\n- всё главное",
    }
    llm = ScriptedLLM(answer)
    monkeypatch.setattr(exam, "get_llm", lambda: llm)
    course_id = await create_course(user)

    await exam.build_exam_sheet({}, str(course_id))

    assert len(llm.map_requests) == 3
    assert llm.map_requests[0].startswith("# Пределы\n\n## Предел")
    request = llm.reduce_requests[0]
    assert request["course"] == "Матанализ"
    assert [lecture["title"] for lecture in request["lectures"]] == [t for t, _ in LECTURES]
    content = await saved_sheet(course_id)
    assert {key: content[key] for key in answer} == answer


async def test_empty_reduce_answer_merges_lecture_digests(user, monkeypatch):
    monkeypatch.setattr(exam, "get_llm", ScriptedLLM)
    course_id = await create_course(user)

    await exam.build_exam_sheet({}, str(course_id))

    content = await saved_sheet(course_id)
    assert content["tickets"] == [
        "Билет: Пределы",
        "Общий вопрос",
        "Билет: Производная",
        "Билет: Интеграл",
    ]
    terms = [definition["term"] for definition in content["definitions"]]
    assert terms == ["Пределы", "функция", "Производная", "Интеграл"]
    assert content["cheatsheet_md"].startswith("## Пределы\n\n- главное про Пределы")


async def test_rebuild_replaces_previous_sheet(user, monkeypatch):
    course_id = await create_course(user)
    await exam.build_exam_sheet({}, str(course_id))

    answer = {"tickets": ["Новый билет"], "definitions": [], "cheatsheet_md": "- новое"}
    monkeypatch.setattr(exam, "get_llm", lambda: ScriptedLLM(answer))
    await exam.build_exam_sheet({}, str(course_id))

    assert (await saved_sheet(course_id))["tickets"] == ["Новый билет"]


async def test_broken_reduce_keeps_previous_sheet(user, monkeypatch):
    course_id = await create_course(user)
    await exam.build_exam_sheet({}, str(course_id))
    before = await saved_sheet(course_id)

    class BrokenReduceLLM(ScriptedLLM):
        async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
            if system == load_prompt("exam_reduce"):
                return "не JSON"
            return await super().complete(system, user, json_mode=json_mode)

    monkeypatch.setattr(exam, "get_llm", BrokenReduceLLM)
    with pytest.raises(ValueError, match="не в формате JSON"):
        await exam.build_exam_sheet({}, str(course_id))

    assert await saved_sheet(course_id) == before


async def test_exam_sheet_skips_lectures_without_summary(user):
    course_id = await create_course(user, [("Пустая", ""), *LECTURES[:1]])

    async with SessionLocal() as session:
        notes = await exam.load_course_notes(session, course_id)

    assert [lecture.title for lecture in notes] == ["Пределы"]


async def test_exam_sheet_needs_ai_transfer_consent(user):
    course_id = await create_course(user)
    async with SessionLocal() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(ai_transfer_accepted_at=None)
        )
        await session.commit()

    assert await exam.build_exam_sheet({}, str(course_id)) == "no_consent"
    assert await saved_sheet(course_id) is None


@pytest.fixture
def enqueued(monkeypatch) -> list[uuid.UUID]:
    calls: list[uuid.UUID] = []

    async def fake_enqueue(course_id: uuid.UUID) -> None:
        calls.append(course_id)

    monkeypatch.setattr(exam_api, "enqueue_exam_sheet", fake_enqueue)
    return calls


@pytest.fixture
def in_progress(monkeypatch) -> list[bool]:
    state = [False]

    async def fake_in_progress(course_id: uuid.UUID) -> bool:
        return state[0]

    monkeypatch.setattr(exam_api, "exam_sheet_in_progress", fake_in_progress)
    return state


async def test_exam_sheet_requires_subscription(client, user, auth_headers, enqueued):
    course_id = await create_course(user)
    url = f"/api/v1/courses/{course_id}/exam-sheet"

    for method in ("post", "get"):
        response = await getattr(client, method)(url, headers=auth_headers)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "subscription_required"
    assert enqueued == []


async def test_post_enqueues_and_get_returns_sheet(
    client, user, auth_headers, enqueued, in_progress
):
    await subscribe(user)
    course_id = await create_course(user)
    url = f"/api/v1/courses/{course_id}/exam-sheet"

    response = await client.get(url, headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "exam_sheet_not_found"

    response = await client.post(url, headers=auth_headers)
    assert response.status_code == 202
    assert enqueued == [course_id]

    in_progress[0] = True
    response = await client.get(url, headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "exam_sheet_processing"

    await exam.build_exam_sheet({}, str(enqueued[0]))
    response = await client.get(url, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["course_id"] == str(course_id)
    assert "## Интеграл" in data["cheatsheet_md"]
    assert data["processing"] is True
    assert data["outdated"] is False


async def test_post_without_summaries_conflicts(client, user, auth_headers, enqueued):
    await subscribe(user)
    course_id = await create_course(user, [])

    response = await client.post(f"/api/v1/courses/{course_id}/exam-sheet", headers=auth_headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_summaries"
    assert enqueued == []


async def test_foreign_course_is_not_found(client, user, auth_headers, enqueued, in_progress):
    await subscribe(user)
    async with SessionLocal() as session:
        stranger = User(display_name="Чужой")
        session.add(stranger)
        await session.commit()
    try:
        course_id = await create_course(stranger)
        url = f"/api/v1/courses/{course_id}/exam-sheet"
        for method in ("post", "get"):
            response = await getattr(client, method)(url, headers=auth_headers)
            assert response.status_code == 404
            assert response.json()["detail"] == "Курс не найден"
        assert enqueued == []
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, stranger.id))
            await session.commit()


async def test_broken_map_answer_falls_back_to_outline():
    class BrokenMapLLM:
        async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
            return "не JSON"

    notes = exam.LectureNotes(
        lecture_id=uuid.uuid4(), title="Ряды", content_md="## Ряды\nтекст\n### Признаки\nещё текст"
    )

    digest = await exam.digest_lecture(BrokenMapLLM(), notes)

    assert (digest.tickets, digest.definitions) == ([], [])
    assert digest.cheatsheet_md == "- Ряды\n- Признаки"


async def test_queue_down_returns_503(client, user, auth_headers, monkeypatch):
    await subscribe(user)
    course_id = await create_course(user)

    async def queue_down(course_id: uuid.UUID) -> None:
        raise RedisConnectionError("нет связи")

    monkeypatch.setattr(exam_api, "enqueue_exam_sheet", queue_down)
    monkeypatch.setattr(exam_api, "exam_sheet_in_progress", queue_down)
    url = f"/api/v1/courses/{course_id}/exam-sheet"

    for method in ("post", "get"):
        response = await getattr(client, method)(url, headers=auth_headers)
        assert response.status_code == 503


async def add_lecture(user, course_id, title: str, content_md: str) -> uuid.UUID:
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title=title, source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        session.add(Summary(lecture_id=lecture.id, content_md=content_md))
        await session.execute(
            insert(course_lectures).values(course_id=course_id, lecture_id=lecture.id, position=9)
        )
        await session.commit()
        return lecture.id


async def test_sheet_outdated_after_course_changes(client, user, auth_headers, in_progress):
    await subscribe(user)
    course_id = await create_course(user)
    url = f"/api/v1/courses/{course_id}/exam-sheet"
    await exam.build_exam_sheet({}, str(course_id))
    first = await client.get(url, headers=auth_headers)
    assert (first.json()["outdated"], first.json()["processing"]) == (False, False)

    added = await add_lecture(user, course_id, "Ряды", "## Ряды")
    assert (await client.get(url, headers=auth_headers)).json()["outdated"] is True

    await exam.build_exam_sheet({}, str(course_id))
    assert (await client.get(url, headers=auth_headers)).json()["outdated"] is False

    removed = await client.delete(
        f"/api/v1/courses/{course_id}/lectures/{added}", headers=auth_headers
    )
    assert removed.status_code == 204
    assert (await client.get(url, headers=auth_headers)).json()["outdated"] is True


async def test_lecture_without_summary_does_not_outdate_sheet(
    client, user, auth_headers, in_progress
):
    await subscribe(user)
    course_id = await create_course(user)
    await exam.build_exam_sheet({}, str(course_id))
    await add_lecture(user, course_id, "Ещё обрабатывается", "")
    response = await client.get(f"/api/v1/courses/{course_id}/exam-sheet", headers=auth_headers)
    assert response.json()["outdated"] is False


async def test_sheet_without_lecture_list_is_outdated(client, user, auth_headers, in_progress):
    await subscribe(user)
    course_id = await create_course(user)
    async with SessionLocal() as session:
        session.add(
            ExamSheet(
                course_id=course_id,
                content={"tickets": [], "definitions": [], "cheatsheet_md": "- старое"},
            )
        )
        await session.commit()
    response = await client.get(f"/api/v1/courses/{course_id}/exam-sheet", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["outdated"] is True
