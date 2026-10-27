import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import jwt

from app.api.exam_exports import create_exam_sheet_token
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import ALGORITHM, create_export_token
from app.models import Course, ExamSheet, User
from app.services.pdf import exam_sheet_html
from tests.test_exam_sheet import subscribe
from tests.test_export_pdf import pdf_objects

CONTENT = {
    "tickets": ["Предел последовательности", "Производная сложной функции"],
    "definitions": [
        {"term": "Предел", "definition": "Число, к которому стремится последовательность"},
        {"term": "", "definition": "без термина"},
    ],
    "cheatsheet_md": "## Формулы\n- $(x^n)' = n x^{n-1}$",
    "lecture_ids": [],
}


async def create_course(owner: User, content: dict | None = CONTENT) -> Course:
    async with SessionLocal() as session:
        course = Course(owner_id=owner.id, title="Матанализ")
        session.add(course)
        await session.flush()
        if content is not None:
            session.add(ExamSheet(course_id=course.id, content=content))
        await session.commit()
        return course


async def request_link(client, headers, course_id):
    return await client.post(
        f"/api/v1/courses/{course_id}/exam-sheet/exports/pdf/link", headers=headers
    )


def token_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["token"][0]


async def test_link_downloads_pdf_without_header(client, user, auth_headers):
    await subscribe(user)
    course = await create_course(user)

    link = await request_link(client, auth_headers, course.id)

    assert link.status_code == 200
    body = link.json()
    assert urlsplit(body["url"]).path == f"/api/v1/courses/{course.id}/exam-sheet/export.pdf"
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert timedelta(0) < expires_at - datetime.now(UTC) <= timedelta(minutes=2)

    response = await client.get(body["url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.content.startswith(b"%PDF")
    assert f"/courses/{course.id}/exam-sheet".encode() in pdf_objects(response.content)


async def test_pdf_with_bearer(client, user, auth_headers):
    await subscribe(user)
    course = await create_course(user)

    response = await client.get(
        f"/api/v1/courses/{course.id}/exam-sheet/export.pdf", headers=auth_headers
    )

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


async def test_link_requires_subscription(client, user, auth_headers):
    course = await create_course(user)

    response = await request_link(client, auth_headers, course.id)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "subscription_required"


async def test_token_stops_working_without_subscription(client, user):
    course = await create_course(user)
    token, _ = create_exam_sheet_token(user.id, course.id)

    response = await client.get(
        f"/api/v1/courses/{course.id}/exam-sheet/export.pdf", params={"token": token}
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "subscription_required"


async def test_link_requires_auth(client, user):
    course = await create_course(user)

    response = await request_link(client, {}, course.id)

    assert response.status_code == 401


async def test_link_without_sheet(client, user, auth_headers):
    await subscribe(user)
    course = await create_course(user, content=None)

    response = await request_link(client, auth_headers, course.id)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "exam_sheet_not_found"


async def test_foreign_or_missing_course(client, user, auth_headers):
    await subscribe(user)
    async with SessionLocal() as session:
        stranger = User(display_name="Чужой")
        session.add(stranger)
        await session.commit()
    try:
        course = await create_course(stranger)
        foreign = await request_link(client, auth_headers, course.id)
        missing = await request_link(client, auth_headers, uuid.uuid4())
        assert foreign.status_code == 404
        assert missing.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, stranger.id))
            await session.commit()


async def test_token_is_bound_to_course(client, user, auth_headers):
    await subscribe(user)
    first = await create_course(user)
    second = await create_course(user)
    link = (await request_link(client, auth_headers, first.id)).json()

    response = await client.get(
        f"/api/v1/courses/{second.id}/exam-sheet/export.pdf",
        params={"token": token_of(link["url"])},
    )

    assert response.status_code == 403


async def test_lecture_export_token_is_rejected(client, user):
    await subscribe(user)
    course = await create_course(user)
    token, _ = create_export_token(user.id, course.id, "pdf")

    response = await client.get(
        f"/api/v1/courses/{course.id}/exam-sheet/export.pdf", params={"token": token}
    )

    assert response.status_code == 401


async def test_exam_sheet_token_is_not_an_access_token(client, user):
    course = await create_course(user)
    token, _ = create_exam_sheet_token(user.id, course.id)

    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


async def test_expired_token(client, user):
    await subscribe(user)
    course = await create_course(user)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "aud": "exam-sheet-export",
            "scope": "exam-sheet-export",
            "course_id": str(course.id),
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        },
        get_settings().secret_key,
        algorithm=ALGORITHM,
    )

    response = await client.get(
        f"/api/v1/courses/{course.id}/exam-sheet/export.pdf", params={"token": token}
    )

    assert response.status_code == 401


def test_exam_sheet_html_has_all_sections_and_escapes():
    course = Course(id=uuid.uuid4(), title="<b>Матанализ</b>")
    content = {**CONTENT, "tickets": ["<script>alert(1)</script>", *CONTENT["tickets"]]}

    html = exam_sheet_html(course, content, "https://lecturo.test")

    assert "<b>Матанализ</b>" not in html
    assert "<script>" not in html
    assert "Предел последовательности" in html
    assert "Число, к которому стремится последовательность" in html
    assert "без термина" not in html
    assert 'class="katex"' in html
    assert f"https://lecturo.test/courses/{course.id}/exam-sheet" in html


def test_exam_sheet_html_empty_sections():
    course = Course(id=uuid.uuid4(), title="Пусто")

    html = exam_sheet_html(
        course, {"tickets": [], "definitions": [], "cheatsheet_md": " "}, "https://lecturo.test"
    )

    assert "Билетов в памятке нет." in html
    assert "Определений в памятке нет." in html
    assert "Шпаргалки в памятке нет." in html
