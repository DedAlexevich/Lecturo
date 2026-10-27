import hashlib
import uuid

import pytest

from app.core.db import SessionLocal
from app.models import (
    ChunkKind,
    Course,
    Lecture,
    SearchChunk,
    SourceType,
    User,
    course_lectures,
)
from app.providers.openai_compat import OpenAICompatibleError
from app.providers.stub import StubEmbeddings
from app.services import search as search_service
from app.services.search import KEYWORD_BONUS, LIMIT, MARGIN, add_prefixes, relevant


class TopicEmbeddings(StubEmbeddings):
    def _vector(self, text: str) -> list[float]:
        topic = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4]) % self.dimension
        return [float(idx == topic) for idx in range(self.dimension)]


@pytest.fixture(autouse=True)
def topic_embeddings(monkeypatch):
    monkeypatch.setattr(search_service, "get_embeddings", TopicEmbeddings)


async def create_lecture(owner_id: uuid.UUID, title: str, *texts: str) -> uuid.UUID:
    vectors = await TopicEmbeddings().embed_documents(list(texts))
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


async def test_rejects_both_scopes(client, auth_headers):
    response = await search(
        client,
        auth_headers,
        q="интеграл",
        lecture_id=str(uuid.uuid4()),
        course_id=str(uuid.uuid4()),
    )

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


def test_relevant_ranks_by_meaning_with_small_keyword_bonus():
    scores = relevant({1: 0.5, 2: 0.48, 3: 0.4}, {2, 3})

    assert sorted(scores, key=scores.__getitem__, reverse=True) == [2, 1, 3]
    assert scores[2] == pytest.approx(0.48 + KEYWORD_BONUS)


def test_relevant_drops_hits_far_below_best():
    scores = relevant({1: 0.5, 2: 0.5 - MARGIN - 0.01, 3: 0.1}, {3})

    assert set(scores) == {1}


def test_relevant_drops_weak_hits_without_keywords():
    assert set(relevant({1: 0.15, 2: 0.1}, {2})) == {2}


def test_relevant_handles_no_candidates():
    assert relevant({}, set()) == {}


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


async def add_chunk(lecture_id: uuid.UUID, kind: ChunkKind, text: str, **fields) -> None:
    [vector] = await TopicEmbeddings().embed_documents([text])
    async with SessionLocal() as session:
        session.add(
            SearchChunk(lecture_id=lecture_id, kind=kind, text=text, embedding=vector, **fields)
        )
        await session.commit()


async def test_global_search_covers_all_own_lectures_and_kinds(client, user, auth_headers):
    first = await create_lecture(user.id, "Первая", "Несобственный интеграл")
    second = await create_lecture(user.id, "Вторая", "Пределы последовательностей")
    await add_chunk(second, ChunkKind.chapter, "Интеграл Римана", start=60.0, end=120.0)
    await add_chunk(second, ChunkKind.summary, "Свойства интеграла", section=2)

    response = await search(client, auth_headers, q="интеграл")

    assert response.status_code == 200
    hits = {(hit["lecture_id"], hit["kind"]): hit for hit in response.json()}
    assert set(hits) >= {
        (str(first), "transcript"),
        (str(second), "chapter"),
        (str(second), "summary"),
    }
    chapter = hits[(str(second), "chapter")]
    assert (chapter["start"], chapter["end"], chapter["section"]) == (60.0, 120.0, None)
    summary = hits[(str(second), "summary")]
    assert (summary["start"], summary["section"], summary["lecture_title"]) == (None, 2, "Вторая")


async def test_global_search_hides_foreign_lectures(client, user, auth_headers, stranger):
    own = await create_lecture(user.id, "Своя", "Интеграл по контуру")
    foreign = await create_lecture(stranger.id, "Чужая", "Интеграл по контуру")
    await add_chunk(foreign, ChunkKind.summary, "Интеграл по контуру", section=0)

    response = await search(client, auth_headers, q="интеграл по контуру")

    lecture_ids = {hit["lecture_id"] for hit in response.json()}
    assert str(own) in lecture_ids
    assert str(foreign) not in lecture_ids


async def test_scoped_search_returns_only_transcript(client, user, auth_headers):
    lecture_id = await create_lecture(user.id, "Лекция", "Интеграл Лебега")
    await add_chunk(lecture_id, ChunkKind.chapter, "Интеграл Римана", start=0.0, end=60.0)
    await add_chunk(lecture_id, ChunkKind.summary, "Интеграл Стилтьеса", section=0)
    course_id = await create_course(user.id, lecture_id)

    by_lecture = await search(client, auth_headers, q="интеграл", lecture_id=str(lecture_id))
    by_course = await search(client, auth_headers, q="интеграл", course_id=str(course_id))

    for response in (by_lecture, by_course):
        assert [(hit["kind"], hit["text"]) for hit in response.json()] == [
            ("transcript", "Интеграл Лебега")
        ]


async def test_global_search_finds_meaning_without_shared_words(
    client, user, auth_headers, monkeypatch
):
    lecture_id = await create_lecture(user.id, "Матанализ", "Скорость изменения функции")
    await add_chunk(lecture_id, ChunkKind.chapter, "Ряды Фурье", start=0.0, end=60.0)
    [target] = await TopicEmbeddings().embed_documents(["Скорость изменения функции"])

    class MeaningEmbeddings(TopicEmbeddings):
        async def embed_query(self, text: str) -> list[float]:
            return target

    monkeypatch.setattr(search_service, "get_embeddings", MeaningEmbeddings)

    response = await search(client, auth_headers, q="производная")

    assert response.json()[0]["text"] == "Скорость изменения функции"


async def test_meaning_outranks_keyword_noise(client, user, auth_headers, monkeypatch):
    lecture_id = await create_lecture(
        user.id, "Лекция", "Скорость изменения функции", "Скачайте курс по производной"
    )
    [target] = await TopicEmbeddings().embed_documents(["Скорость изменения функции"])

    class MeaningEmbeddings(TopicEmbeddings):
        async def embed_query(self, text: str) -> list[float]:
            return target

    monkeypatch.setattr(search_service, "get_embeddings", MeaningEmbeddings)

    response = await search(client, auth_headers, q="производная", lecture_id=str(lecture_id))

    assert [hit["text"] for hit in response.json()] == ["Скорость изменения функции"]


def test_relevant_keeps_keyword_hits_without_embedding():
    scores = relevant({1: 0.9}, {2})

    assert set(scores) == {1, 2}


async def test_finds_keyword_chunk_without_embedding(client, user, auth_headers):
    lecture_id = await create_lecture(user.id, "Лекция", "Пределы последовательностей")
    async with SessionLocal() as session:
        session.add(SearchChunk(lecture_id=lecture_id, text="Определённые интегралы"))
        await session.commit()

    response = await search(client, auth_headers, q="интеграл", lecture_id=str(lecture_id))

    assert [hit["text"] for hit in response.json()] == ["Определённые интегралы"]
