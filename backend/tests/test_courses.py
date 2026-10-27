import uuid

from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import Lecture, SourceType, User


async def create_lectures(owner_id: uuid.UUID, *titles: str) -> list[uuid.UUID]:
    async with SessionLocal() as session:
        lectures = [
            Lecture(owner_id=owner_id, title=title, source_type=SourceType.upload)
            for title in titles
        ]
        session.add_all(lectures)
        await session.commit()
        return [lecture.id for lecture in lectures]


async def create_course(client, headers, title: str) -> dict:
    response = await client.post("/api/v1/courses", json={"title": title}, headers=headers)
    assert response.status_code == 201
    return response.json()


async def test_course_crud(client, auth_headers):
    course = await create_course(client, auth_headers, "Матанализ")
    assert course["lecture_count"] == 0

    updated = await client.patch(
        f"/api/v1/courses/{course['id']}",
        json={"description": "Первый семестр"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Матанализ"
    assert updated.json()["description"] == "Первый семестр"

    listed = await client.get("/api/v1/courses", headers=auth_headers)
    assert [item["id"] for item in listed.json()] == [course["id"]]

    deleted = await client.delete(f"/api/v1/courses/{course['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/courses/{course['id']}", headers=auth_headers)
    assert missing.status_code == 404


async def test_lecture_in_several_courses(client, user, auth_headers):
    first_lecture, second_lecture = await create_lectures(user.id, "Пределы", "Ряды")
    first = await create_course(client, auth_headers, "Матанализ")
    second = await create_course(client, auth_headers, "Подготовка к экзамену")

    for course_id, lecture_id in (
        (first["id"], second_lecture),
        (first["id"], first_lecture),
        (first["id"], first_lecture),
        (second["id"], first_lecture),
    ):
        response = await client.post(
            f"/api/v1/courses/{course_id}/lectures",
            json={"lecture_id": str(lecture_id)},
            headers=auth_headers,
        )
        assert response.status_code == 204

    lectures = await client.get(f"/api/v1/courses/{first['id']}/lectures", headers=auth_headers)
    assert [item["title"] for item in lectures.json()] == ["Ряды", "Пределы"]
    listed = await client.get("/api/v1/courses", headers=auth_headers)
    counts = {item["id"]: item["lecture_count"] for item in listed.json()}
    assert counts == {first["id"]: 2, second["id"]: 1}

    removed = await client.delete(
        f"/api/v1/courses/{first['id']}/lectures/{second_lecture}", headers=auth_headers
    )
    assert removed.status_code == 204
    again = await client.delete(
        f"/api/v1/courses/{first['id']}/lectures/{second_lecture}", headers=auth_headers
    )
    assert again.status_code == 404
    course = await client.get(f"/api/v1/courses/{first['id']}", headers=auth_headers)
    assert course.json()["lecture_count"] == 1


async def test_delete_course_keeps_lectures(client, user, auth_headers):
    (lecture_id,) = await create_lectures(user.id, "Пределы")
    course = await create_course(client, auth_headers, "Матанализ")
    await client.post(
        f"/api/v1/courses/{course['id']}/lectures",
        json={"lecture_id": str(lecture_id)},
        headers=auth_headers,
    )

    await client.delete(f"/api/v1/courses/{course['id']}", headers=auth_headers)

    lecture = await client.get(f"/api/v1/lectures/{lecture_id}", headers=auth_headers)
    assert lecture.status_code == 200


async def test_foreign_course_and_lecture_hidden(client, user, auth_headers):
    async with SessionLocal() as session:
        stranger = User(display_name="Чужой")
        session.add(stranger)
        await session.commit()
    stranger_headers = {"Authorization": f"Bearer {create_access_token(stranger.id)}"}
    try:
        (foreign_lecture,) = await create_lectures(stranger.id, "Чужая лекция")
        foreign = await create_course(client, stranger_headers, "Чужой курс")
        own = await create_course(client, auth_headers, "Мой курс")

        for method, path in (
            ("GET", f"/api/v1/courses/{foreign['id']}"),
            ("PATCH", f"/api/v1/courses/{foreign['id']}"),
            ("DELETE", f"/api/v1/courses/{foreign['id']}"),
            ("GET", f"/api/v1/courses/{foreign['id']}/lectures"),
            ("POST", f"/api/v1/courses/{foreign['id']}/lectures"),
            ("DELETE", f"/api/v1/courses/{foreign['id']}/lectures/{foreign_lecture}"),
        ):
            response = await client.request(
                method,
                path,
                json={"lecture_id": str(foreign_lecture)},
                headers=auth_headers,
            )
            assert response.status_code == 404

        kept = await client.get(f"/api/v1/courses/{foreign['id']}", headers=stranger_headers)
        assert kept.status_code == 200
        assert kept.json()["title"] == "Чужой курс"

        added = await client.post(
            f"/api/v1/courses/{own['id']}/lectures",
            json={"lecture_id": str(foreign_lecture)},
            headers=auth_headers,
        )
        assert added.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, stranger.id))
            await session.commit()


async def test_list_courses_of_lecture(client, user, auth_headers):
    first_lecture, second_lecture = await create_lectures(user.id, "Пределы", "Ряды")
    first = await create_course(client, auth_headers, "Матанализ")
    second = await create_course(client, auth_headers, "Подготовка к экзамену")
    await create_course(client, auth_headers, "Физика")
    for course_id in (first["id"], second["id"]):
        await client.post(
            f"/api/v1/courses/{course_id}/lectures",
            json={"lecture_id": str(first_lecture)},
            headers=auth_headers,
        )

    listed = await client.get(
        "/api/v1/courses", params={"lecture_id": str(first_lecture)}, headers=auth_headers
    )
    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()} == {first["id"], second["id"]}
    assert all(item["lecture_count"] == 1 for item in listed.json())

    empty = await client.get(
        "/api/v1/courses", params={"lecture_id": str(second_lecture)}, headers=auth_headers
    )
    assert empty.json() == []
