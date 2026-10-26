import json

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Chapter, Lecture, SourceType, Summary, TranscriptSegment
from app.pipeline import summarize
from app.pipeline.summarize import PartDigest, Topic, build_chapters, split_into_parts


def make_segments(bounds: list[tuple[float, float]]) -> list[TranscriptSegment]:
    return [TranscriptSegment(start=s, end=e, text=f"фраза {s:g}") for s, e in bounds]


def minute_segments(minutes: int) -> list[TranscriptSegment]:
    return make_segments([(m * 60.0, m * 60.0 + 59.0) for m in range(minutes)])


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (0, []),
        (10, [(0, 599)]),
        (15, [(0, 899)]),
        (30, [(0, 899), (900, 1799)]),
        (34, [(0, 899), (900, 2039)]),
        (40, [(0, 899), (900, 1799), (1800, 2399)]),
        (60, [(0, 899), (900, 1799), (1800, 2699), (2700, 3599)]),
    ],
)
def test_split_into_parts(minutes, expected):
    parts = split_into_parts(minute_segments(minutes))
    assert [(p[0].start, p[-1].end) for p in parts] == expected


def test_split_into_parts_keeps_every_segment_in_order():
    segments = minute_segments(95)
    parts = split_into_parts(segments)
    assert [s for part in parts for s in part] == segments


def test_chapters_cover_lecture_without_overlaps():
    segments = minute_segments(60)
    raw = [
        {"title": "Пределы", "start": 1810, "summary": "Определение предела."},
        {"title": "Введение", "start": 25, "summary": "О курсе."},
        {"title": "Повтор", "start": 1805},
        {"title": "", "start": 100},
        {"title": "Без таймкода"},
        {"title": "Ряды", "start": "2725"},
        "мусор",
    ]

    chapters = build_chapters(raw, segments, [])

    assert [c.title for c in chapters] == ["Введение", "Пределы", "Ряды"]
    assert [(c.start, c.end) for c in chapters] == [(0, 1800), (1800, 2700), (2700, 3599)]
    assert chapters[0].summary == "О курсе."


def test_chapters_fall_back_to_parts():
    segments = minute_segments(30)
    digests = [
        PartDigest(start=0, end=899, summary="Первая.", topics=[Topic("Множества", 0)]),
        PartDigest(start=900, end=1799, summary="Вторая.", topics=[]),
    ]

    chapters = build_chapters(None, segments, digests)

    assert [(c.title, c.start, c.end) for c in chapters] == [
        ("Множества", 0, 900),
        ("Часть 2", 900, 1799),
    ]


class ScriptedLLM:
    def __init__(self) -> None:
        self.requests: list[str] = []

    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        assert json_mode
        self.requests.append(user)
        if system == summarize.load_prompt("map"):
            start = int(user.split("]", 1)[0].lstrip("["))
            return json.dumps(
                {
                    "summary": f"Часть с {start}",
                    "topics": [{"title": f"Тема {start}", "start": start}],
                }
            )
        parts = json.loads(user)["parts"]
        chapters = [
            {"title": f"Глава {i}", "start": part["start"] + 20, "summary": part["summary"]}
            for i, part in enumerate(parts, start=1)
        ]
        return "```json\n" + json.dumps({"chapters": chapters, "summary_md": "## Итог"}) + "\n```"


async def create_transcribed_lecture(user, minutes: int) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title="Матанализ", source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        session.add_all(
            TranscriptSegment(lecture_id=lecture.id, idx=i, start=s.start, end=s.end, text=s.text)
            for i, s in enumerate(minute_segments(minutes))
        )
        await session.commit()
        return lecture


async def run_summarize(lecture_id) -> list[float]:
    reported = []

    async def report(progress):
        reported.append(progress)

    async with SessionLocal() as session:
        lecture = await session.get(Lecture, lecture_id)
        await summarize.summarize(session, lecture, report)
        await session.commit()
    return reported


async def saved(lecture_id) -> tuple[list[Chapter], Summary | None]:
    async with SessionLocal() as session:
        chapters = await session.scalars(
            select(Chapter).where(Chapter.lecture_id == lecture_id).order_by(Chapter.idx)
        )
        return list(chapters), await session.get(Summary, lecture_id)


async def test_summarize_maps_parts_and_saves_chapters(user, monkeypatch):
    llm = ScriptedLLM()
    monkeypatch.setattr(summarize, "get_llm", lambda: llm)
    lecture = await create_transcribed_lecture(user, 60)

    reported = await run_summarize(lecture.id)

    assert len(llm.requests) == 5
    assert reported == pytest.approx([0.2, 0.4, 0.6, 0.8])
    chapters, summary = await saved(lecture.id)
    assert summary.content_md == "## Итог"
    assert [c.title for c in chapters] == ["Глава 1", "Глава 2", "Глава 3", "Глава 4"]
    assert [(c.start, c.end) for c in chapters] == [
        (0, 900),
        (900, 1800),
        (1800, 2700),
        (2700, 3599),
    ]
    assert chapters[1].summary == "Часть с 900"


async def test_summarize_on_stub_llm_replaces_previous_result(user):
    lecture = await create_transcribed_lecture(user, 20)

    await run_summarize(lecture.id)
    await run_summarize(lecture.id)

    chapters, summary = await saved(lecture.id)
    assert [(c.start, c.end) for c in chapters] == [(0, 1199)]
    assert summary.content_md
