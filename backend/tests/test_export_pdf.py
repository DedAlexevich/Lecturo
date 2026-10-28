import asyncio
import re
import time
import uuid
import zlib
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Chapter, Lecture, SourceType, Summary, User
from app.services import pdf
from app.services.pdf import format_timecode, lecture_html, render_pdf, render_pdf_limited


def pdf_objects(content: bytes) -> bytes:
    streams = re.findall(rb"stream\r?\n(.*?)\nendstream", content, re.S)
    inflated = []
    for stream in streams:
        try:
            inflated.append(zlib.decompressobj().decompress(stream))
        except zlib.error:
            continue
    return content + b"".join(inflated)


async def create_lecture(owner: User, with_summary: bool = True) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=owner.id,
            title="Линейная алгебра: собственные векторы",
            source_type=SourceType.upload,
            duration_sec=5400,
        )
        session.add(lecture)
        await session.flush()
        if with_summary:
            session.add_all(
                [
                    Chapter(
                        lecture_id=lecture.id,
                        idx=0,
                        start=0,
                        end=754,
                        title="Определения",
                        summary="Что такое собственный вектор и собственное число.",
                    ),
                    Chapter(
                        lecture_id=lecture.id,
                        idx=1,
                        start=754.6,
                        end=5400,
                        title="Характеристический многочлен",
                    ),
                    Summary(
                        lecture_id=lecture.id,
                        content_md="## Определения\n- **Собственный вектор**: Av = λv\n",
                    ),
                ]
            )
        await session.commit()
        return lecture


async def test_export_pdf(client, user, auth_headers):
    lecture = await create_lecture(user)

    response = await client.get(f"/api/v1/lectures/{lecture.id}/export.pdf", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert 'filename="lecture.pdf"' in response.headers["content-disposition"]
    assert "filename*=UTF-8''%D0%9B" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")
    objects = pdf_objects(response.content)
    assert f"/lectures/{lecture.id}?t=754".encode() in objects
    assert re.search(rb"/FontName /\w+\+(Inter|DejaVu)", objects)


async def test_export_pdf_foreign_lecture(client, auth_headers):
    async with SessionLocal() as session:
        stranger = User(display_name="Чужой", ai_transfer_accepted_at=datetime.now(UTC))
        session.add(stranger)
        await session.commit()
    try:
        lecture = await create_lecture(stranger)
        response = await client.get(
            f"/api/v1/lectures/{lecture.id}/export.pdf", headers=auth_headers
        )
        assert response.status_code == 404
    finally:
        async with SessionLocal() as session:
            await session.delete(await session.get(User, stranger.id))
            await session.commit()

    missing = await client.get(f"/api/v1/lectures/{uuid.uuid4()}/export.pdf", headers=auth_headers)
    assert missing.status_code == 404


async def test_export_pdf_requires_auth(client):
    response = await client.get(f"/api/v1/lectures/{uuid.uuid4()}/export.pdf")
    assert response.status_code == 401


async def test_export_pdf_not_ready(client, user, auth_headers):
    lecture = await create_lecture(user, with_summary=False)

    response = await client.get(f"/api/v1/lectures/{lecture.id}/export.pdf", headers=auth_headers)

    assert response.status_code == 409

    async with SessionLocal() as session:
        session.add(Summary(lecture_id=lecture.id, content_md="  \n"))
        await session.commit()

    blank = await client.get(f"/api/v1/lectures/{lecture.id}/export.pdf", headers=auth_headers)

    assert blank.status_code == 409


def test_lecture_html_escapes_content():
    lecture = Lecture(
        id=uuid.uuid4(),
        title="<b>Лекция</b>",
        source_type=SourceType.upload,
        created_at=datetime(2026, 3, 1, 22, 30, tzinfo=UTC),
        chapters=[],
        summary=Summary(content_md='<img src="http://10.0.0.1/x">\n\n<script>alert(1)</script>'),
    )

    html = lecture_html(lecture, "https://lecturo.test")

    assert "<b>Лекция</b>" not in html
    assert "<script>" not in html
    assert "<img" not in html
    assert "02.03.2026" in html


def test_format_timecode():
    assert format_timecode(5) == "0:05"
    assert format_timecode(754.6) == "12:34"
    assert format_timecode(3725) == "1:02:05"


def test_pdf_renders_formula_with_embedded_fonts():
    lecture = Lecture(
        id=uuid.uuid4(),
        title="Линейная алгебра",
        source_type=SourceType.upload,
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
        chapters=[],
        summary=Summary(content_md=":::theorem\nФормула $x^2$\n:::\n\n$$\\frac{a}{b}$$"),
    )

    html = lecture_html(lecture, "https://lecturo.test")
    result = render_pdf(html)

    assert 'class="summary-callout summary-callout--theorem"' in html
    assert 'class="katex-display"' in html
    assert 'class="mfrac"' in html
    assert result.startswith(b"%PDF")
    objects = pdf_objects(result)
    assert b"KaTeX" in objects
    assert b"DejaVu" in objects or b"Inter" in objects


async def test_export_pdf_rate_limit(client, user, auth_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "pdf_export_rate_limit", 1)
    monkeypatch.setattr(pdf, "render_pdf", lambda html: b"%PDF-1.7")
    lecture = await create_lecture(user)
    url = f"/api/v1/lectures/{lecture.id}/export.pdf"

    first = await client.get(url, headers=auth_headers)
    second = await client.get(url, headers=auth_headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == "Слишком много выгрузок PDF, попробуйте через минуту"


async def test_pdf_renders_are_limited(monkeypatch):
    running = 0
    peak = 0

    def slow_render(html: str) -> bytes:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        time.sleep(0.05)
        running -= 1
        return b"%PDF"

    monkeypatch.setattr(pdf, "render_pdf", slow_render)
    monkeypatch.setattr(pdf, "pdf_renders", asyncio.Semaphore(2))

    results = await asyncio.gather(*(render_pdf_limited("<p></p>") for _ in range(6)))

    assert results == [b"%PDF"] * 6
    assert peak == 2
