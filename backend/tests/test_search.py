import uuid

import pytest

from app.core.db import SessionLocal
from app.models import Course, Lecture, SearchChunk, SourceType, User, course_lectures
from app.providers.openai_compat import OpenAICompatibleError
from app.providers.stub import StubEmbeddings
from app.services import search as search_service
from app.services.search import LIMIT, RRF_K, add_prefixes, rrf


async def create_lecture(owner_id: uuid.UUID, title: str, *texts: str) -> uuid.UUID:
    vectors = await StubEmbeddings().embed_documents(list(texts))
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=owner_id, title=title, source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        session.add_all(
            SearchChunk(
                lecture_id=lecture.id,
                start=idx * 45.0,
                end=(idx + 1) * 45.0,
                text=text,
                embedding=vector,
            )
            for idx, (text, vector) in enumerate(zip(texts, vectors, strict=True))
        )
        await session.commit()
        return lecture.id


async def create_course(owner_id: uuid.UUID, *lecture_ids: uuid.UUID) -> uuid.UUID:
    async with SessionLocal() as session:
        course = Course(owner_id=owner_id, title="Матанализ")
        session.add(course)
        await session.flush()
        if lecture_ids:
            await session.execute(
                course_lectures.insert(),
                [{"course_id": course.id, "lecture_id": lecture_id} for lecture_id in lecture_ids],
            )
        await session.commit()
        return course.id


@pytest.fixture
async def stranger():
    async with SessionLocal() as session:
        user = User(display_name="Чужой")
        session.add(user)
        await session.commit()
        yield user
        await session.delete(user)
        await session.commit()


async def search(client, headers, **params):
    return await client.get("/api/v1/search", params=params, headers=headers)


@pytest.mark.parametrize("q", ["интеграл", "интегралы", "интегралами"])
async def test_fulltext_finds_word_forms(client, user, auth_headers, q):
    lecture_id = await create_lecture(
        user.id,
        "Интегралы",
        "Сегодня поговорим о пределах последовательностей.",
        "Определённые интегралы считаются по формуле Ньютона — Лейбница.",
        "Ряды Тейлора пригодятся на следующем занятии.",
    )

    response = await search(client, auth_headers, q=q, lecture_id=str(lecture_id))

    assert response.status_code == 200
    hits = response.json()
    assert hits[0]["text"].startswith("Определённые интегралы")
    assert hits[0]["start"] == 45.0
    assert hits[0]["end"] == 90.0
    assert hits[0]["lecture_id"] == str(lecture_id)
    assert hits[0]["lecture_title"] == "Интегралы"
    assert hits[0]["score"] > hits[1]["score"]
    assert [hit["score"] for hit in hits] == sorted((hit["score"] for hit in hits), reverse=True)


async def test_exact_text_ranks_first_by_meaning(client, user, auth_headers):
    texts = [f"фрагмент номер {idx}" for idx in range(5)]
    lecture_id = await create_lecture(user.id, "Лекция", *texts)

    response = await search(client, auth_headers, q=texts[3], lecture_id=str(lecture_id))

    assert response.json()[0]["text"] == texts[3]


@pytest.mark.parametrize("q", ["и в на", "it's", '"формула'])
async def test_odd_queries_do_not_fail(client, user, auth_headers, q):
    lecture_id = await create_lecture(user.id, "Лекция", "Формула Ньютона — Лейбница")

    response = await search(client, auth_headers, q=q, lecture_id=str(lecture_id))

    assert response.status_code == 200


class BrokenEmbeddings(StubEmbeddings):
    async def embed_query(self, text: str) -> list[float]:
        raise OpenAICompatibleError("/embeddings: нет ответа от API")


async def test_falls_back_to_fulltext_when_embeddings_fail(client, user, auth_headers, monkeypatch):
    lecture_id = await create_lecture(
        user.id, "Лекция", "Пределы последовательностей", "Определённые интегралы"
    )
    monkeypatch.setattr(search_service, "get_embeddings", BrokenEmbeddings)

    response = await search(client, auth_headers, q="интеграл", lecture_id=str(lecture_id))

    assert response.status_code == 200
    assert [hit["text"] for hit in response.json()] == ["Определённые интегралы"]


async def test_course_search_covers_only_course_lectures(client, user, auth_headers):
    first = await create_lecture(user.id, "Первая", "Интегралы по частям")
    second = await create_lecture(user.id, "Вторая", "Несобственный интеграл")
    outside = await create_lecture(user.id, "Вне курса", "Интегралы с параметром")
    course_id = await create_course(user.id, first, second)

    response = await search(client, auth_headers, q="интеграл", course_id=str(course_id))

    assert response.status_code == 200
    lecture_ids = {hit["lecture_id"] for hit in response.json()}
    assert lecture_ids == {str(first), str(second)}
    assert str(outside) not in lecture_ids


async def test_search_returns_at_most_limit_hits(client, user, auth_headers):
    lecture_id = await create_lecture(
        user.id, "Длинная", *(f"интеграл, часть {idx}" for idx in range(LIMIT + 5))
    )

    response = await search(client, auth_headers, q="интеграл", lecture_id=str(lecture_id))

    assert len(response.json()) == LIMIT


async def test_empty_course_returns_nothing(client, user, auth_headers):
    course_id = await create_course(user.id)

    response = await search(client, auth_headers, q="интеграл", course_id=str(course_id))

    assert response.status_code == 200
    assert response.json() == []


async def test_foreign_lecture_and_course_are_hidden(client, auth_headers, stranger):
    lecture_id = await create_lecture(stranger.id, "Чужая", "Интегралы")
    course_id = await create_course(stranger.id, lecture_id)

    by_lecture = await search(client, auth_headers, q="интеграл", lecture_id=str(lecture_id))
    by_course = await search(client, auth_headers, q="интеграл", course_id=str(course_id))

    assert by_lecture.status_code == 404
    assert by_course.status_code == 404


@pytest.mark.parametrize("both", [True, False])
async def test_requires_exactly_one_scope(client, auth_headers, both):
    params = {"lecture_id": str(uuid.uuid4()), "course_id": str(uuid.uuid4())} if both else {}

    response = await search(client, auth_headers, q="интеграл", **params)

    assert response.status_code == 422


@pytest.mark.parametrize("q", ["   ", " я "])
async def test_rejects_blank_query(client, user, auth_headers, q):
    lecture_id = await create_lecture(user.id, "Лекция", "Интегралы")

    response = await search(client, auth_headers, q=q, lecture_id=str(lecture_id))

    assert response.status_code == 422


async def test_requires_login(client):
    response = await client.get(
        "/api/v1/search", params={"q": "интеграл", "lecture_id": str(uuid.uuid4())}
    )

    assert response.status_code == 401


def test_rrf_sums_reciprocal_ranks():
    scores = rrf([[1, 2], [2, 3]])

    assert scores == {
        1: 1 / (RRF_K + 1),
        2: 1 / (RRF_K + 2) + 1 / (RRF_K + 1),
        3: 1 / (RRF_K + 2),
    }


@pytest.mark.parametrize(
    ("stemmed", "expected"),
    [
        ("'интегра'", "'интегра':*"),
        ("'ряд'", "'ряд'"),
        ("'интегра' & !'ряд'", "'интегра':* & !'ряд'"),
        ("'формул' <-> 'ньютон'", "'формул':* <-> 'ньютон':*"),
        ("'it''s' | 'ok'", "'it''s':* | 'ok'"),
    ],
)
def test_add_prefixes_only_to_long_lexemes(stemmed, expected):
    assert add_prefixes(stemmed) == expected


async def test_short_word_matches_exactly(client, user, auth_headers, monkeypatch):
    monkeypatch.setattr(search_service, "get_embeddings", BrokenEmbeddings)
    lecture_id = await create_lecture(user.id, "Лекция", "Мат в три хода", "Математика")

    response = await search(client, auth_headers, q="мат", lecture_id=str(lecture_id))

    assert [hit["text"] for hit in response.json()] == ["Мат в три хода"]
