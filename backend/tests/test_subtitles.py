import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import unquote

import pytest

from app.core.db import SessionLocal
from app.models import Lecture, SourceType, TranscriptSegment, User
from app.services.subtitles import (
    LINE_WIDTH,
    content_disposition,
    format_timestamp,
    safe_filename,
    split_segment,
    to_srt,
    to_vtt,
)


@dataclass
class Seg:
    start: float
    end: float
    text: str


def test_format_timestamp():
    assert format_timestamp(0, ",") == "00:00:00,000"
    assert format_timestamp(3725.5, ",") == "01:02:05,500"
    assert format_timestamp(59.9996, ".") == "00:01:00.000"
    assert format_timestamp(-1, ".") == "00:00:00.000"


def test_short_segment_is_single_cue():
    cues = split_segment(Seg(1.0, 2.0, "  Привет,\n  мир  "))
    assert len(cues) == 1
    assert cues[0].lines == ["Привет, мир"]
    assert (cues[0].start, cues[0].end) == (1.0, 2.0)


def test_long_segment_is_split_into_cues():
    text = " ".join(["слово"] * 60)
    cues = split_segment(Seg(10.0, 40.0, text))
    assert len(cues) > 1
    assert all(len(cue.lines) <= 2 for cue in cues)
    assert all(len(line) <= LINE_WIDTH for cue in cues for line in cue.lines)
    assert cues[0].start == 10.0
    assert cues[-1].end == pytest.approx(40.0)
    assert all(a.end == b.start for a, b in zip(cues, cues[1:], strict=False))
    assert " ".join(line for cue in cues for line in cue.lines) == text


def test_empty_segment_is_skipped():
    assert split_segment(Seg(0, 1, "   ")) == []


def test_to_srt():
    srt = to_srt([Seg(0.0, 1.5, "раз"), Seg(61.25, 63.0, "два")])
    assert srt == (
        "1\n00:00:00,000 --> 00:00:01,500\nраз\n\n2\n00:01:01,250 --> 00:01:03,000\nдва\n\n"
    )


def test_to_vtt():
    vtt = to_vtt([Seg(0.0, 1.5, "a < b & c")])
    assert vtt == "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\na &lt; b &amp; c\n\n"


def test_safe_filename():
    assert safe_filename('Лекция 1: "Пределы" / часть 2') == "Лекция 1 Пределы часть 2"
    assert safe_filename(" ... ") == "lecture"
    assert safe_filename("a\x7fb") == "a b"
    assert safe_filename("x" * 149 + " .y") == "x" * 149


def test_content_disposition():
    header = content_disposition("Матанализ 1", "srt")
    assert header.startswith('attachment; filename="lecture.srt"; ')
    assert unquote(header.split("filename*=UTF-8''")[1]) == "Матанализ 1.srt"
    assert content_disposition("Calculus 1", "vtt").startswith(
        'attachment; filename="Calculus 1.vtt"; '
    )


@pytest.fixture
async def stranger() -> AsyncIterator[User]:
    async with SessionLocal() as session:
        stranger = User(display_name="Чужой")
        session.add(stranger)
        await session.commit()
        yield stranger
        await session.delete(stranger)
        await session.commit()


async def create_lecture(owner: User, segments: list[Seg]) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=owner.id, title="Матанализ", source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        session.add_all(
            TranscriptSegment(
                lecture_id=lecture.id, idx=idx, start=seg.start, end=seg.end, text=seg.text
            )
            for idx, seg in enumerate(segments)
        )
        await session.commit()
        return lecture


async def test_export_srt(client, user, auth_headers):
    lecture = await create_lecture(user, [Seg(0.0, 2.0, "раз"), Seg(2.0, 4.0, "два")])

    response = await client.get(f"/api/v1/lectures/{lecture.id}/export.srt", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-subrip")
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.text.startswith("1\n00:00:00,000 --> 00:00:02,000\nраз\n\n2\n")


async def test_export_vtt(client, user, auth_headers):
    lecture = await create_lecture(user, [Seg(0.0, 2.0, "раз")])

    response = await client.get(f"/api/v1/lectures/{lecture.id}/export.vtt", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/vtt")
    assert response.text == "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nраз\n\n"


@pytest.mark.parametrize("segments", [[], [Seg(0.0, 1.0, "  "), Seg(1.0, 2.0, "\n")]])
async def test_export_without_transcript(client, user, auth_headers, segments):
    lecture = await create_lecture(user, segments)

    response = await client.get(f"/api/v1/lectures/{lecture.id}/export.srt", headers=auth_headers)
    assert response.status_code == 409


@pytest.mark.parametrize("extension", ["srt", "vtt"])
async def test_foreign_lecture_export_hidden(client, auth_headers, stranger, extension):
    lecture = await create_lecture(stranger, [Seg(0.0, 1.0, "чужое")])

    response = await client.get(
        f"/api/v1/lectures/{lecture.id}/export.{extension}", headers=auth_headers
    )
    assert response.status_code == 404


async def test_missing_lecture_export(client, auth_headers):
    response = await client.get(f"/api/v1/lectures/{uuid.uuid4()}/export.vtt", headers=auth_headers)
    assert response.status_code == 404


async def test_export_requires_auth(client):
    response = await client.get(f"/api/v1/lectures/{uuid.uuid4()}/export.srt")
    assert response.status_code == 401
