import json

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Chapter, Lecture, SourceType, Summary, TranscriptSegment
from app.pipeline import summarize
from app.pipeline.summarize import (
    ChapterDraft,
    PartDigest,
    Topic,
    build_chapters,
    plan_chapters,
    split_into_parts,
    split_oversized,
)


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
        if "фрагмент расшифровки" in system:
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
    assert [c.idx for c in chapters] == list(range(len(chapters)))
    assert chapters[0].start == 0
    assert chapters[-1].end == 1199
    assert summary.content_md


class FailingReduceLLM(ScriptedLLM):
    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if "Главы" in system:
            raise RuntimeError("LLM недоступна")
        return await super().complete(system, user, json_mode=json_mode)


async def test_failed_reduce_keeps_previous_chapters(user, monkeypatch):
    monkeypatch.setattr(summarize, "get_llm", ScriptedLLM)
    lecture = await create_transcribed_lecture(user, 30)
    await run_summarize(lecture.id)
    before = [(c.title, c.start, c.end) for c in (await saved(lecture.id))[0]]

    monkeypatch.setattr(summarize, "get_llm", FailingReduceLLM)
    async with SessionLocal() as session:
        loaded = await session.get(Lecture, lecture.id)

        async def report(progress):
            await session.commit()

        with pytest.raises(RuntimeError):
            await summarize.summarize(session, loaded, report)
        await session.rollback()

    chapters, summary = await saved(lecture.id)
    assert [(c.title, c.start, c.end) for c in chapters] == before
    assert summary.content_md == "## Итог"


class BrokenMapLLM(ScriptedLLM):
    def __init__(self, broken_answers: int) -> None:
        super().__init__()
        self.broken_answers = broken_answers
        self.map_calls = 0

    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if "фрагмент расшифровки" in system and user.startswith("[900]"):
            self.map_calls += 1
            if self.map_calls <= self.broken_answers:
                return "не JSON"
        return await super().complete(system, user, json_mode=json_mode)


async def test_broken_map_answer_is_retried_once():
    llm = BrokenMapLLM(1)
    part = minute_segments(30)[15:]

    digest = await summarize.request_digest(llm, part)

    assert llm.map_calls == 2
    assert digest.summary == "Часть с 900"
    assert (digest.start, digest.end) == (900, 1799)


async def test_part_is_not_lost_after_two_broken_map_answers(user, monkeypatch, caplog):
    llm = BrokenMapLLM(2)
    monkeypatch.setattr(summarize, "get_llm", lambda: llm)
    lecture = await create_transcribed_lecture(user, 60)

    await run_summarize(lecture.id)

    chapters, _ = await saved(lecture.id)
    assert llm.map_calls == 2
    assert chapters[1].start == 900
    assert chapters[1].summary.startswith("фраза 900 фраза 960")
    assert "взят текст расшифровки" in caplog.text


def test_raw_part_summary_is_cut_to_limit():
    part = [
        TranscriptSegment(start=float(i), end=float(i) + 1, text="слово " * 50) for i in range(100)
    ]

    summary = summarize.raw_part_summary(part)

    assert len(summary) <= summarize.RAW_PART_CHAR_LIMIT + 2
    assert summary.endswith(" …")


async def test_broken_reduce_answer_fails_step(user, monkeypatch):
    class BrokenReduceLLM(ScriptedLLM):
        async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
            if "Главы" in system:
                return "не JSON"
            return await super().complete(system, user, json_mode=json_mode)

    monkeypatch.setattr(summarize, "get_llm", BrokenReduceLLM)
    lecture = await create_transcribed_lecture(user, 20)

    with pytest.raises(ValueError, match="не в формате JSON"):
        await run_summarize(lecture.id)


class FlakyReduceLLM(ScriptedLLM):
    def __init__(self, broken_reduces: int) -> None:
        super().__init__()
        self.broken_reduces = broken_reduces
        self.reduce_calls = 0
        self.map_calls = 0

    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if "Главы" in system:
            self.reduce_calls += 1
            if self.reduce_calls <= self.broken_reduces:
                return "не JSON"
        else:
            self.map_calls += 1
        return await super().complete(system, user, json_mode=json_mode)


async def test_broken_first_reduce_answer_is_retried(user, monkeypatch):
    llm = FlakyReduceLLM(1)
    monkeypatch.setattr(summarize, "get_llm", lambda: llm)
    lecture = await create_transcribed_lecture(user, 60)

    await run_summarize(lecture.id)

    chapters, summary = await saved(lecture.id)
    assert llm.reduce_calls == 2
    assert llm.map_calls == 4
    assert summary.content_md == "## Итог"
    assert [c.title for c in chapters] == ["Глава 1", "Глава 2", "Глава 3", "Глава 4"]


async def test_retry_after_failed_reduce_reuses_map_digests(user, monkeypatch):
    llm = FlakyReduceLLM(2)
    monkeypatch.setattr(summarize, "get_llm", lambda: llm)
    lecture = await create_transcribed_lecture(user, 60)

    with pytest.raises(ValueError):
        await run_summarize(lecture.id)
    assert llm.map_calls == 4

    await run_summarize(lecture.id)

    assert llm.map_calls == 4
    assert llm.reduce_calls == 3
    chapters, _ = await saved(lecture.id)
    assert [c.summary for c in chapters] == [f"Часть с {start}" for start in (0, 900, 1800, 2700)]

    await run_summarize(lecture.id)

    assert llm.map_calls == 8


@pytest.mark.parametrize(
    "content",
    [
        '{"summary": "да"}',
        '```json\n{"summary": "да"}\n```',
        'Вот ответ:\n```JSON\n{"summary": "да"}\n```\nГотово.',
    ],
)
def test_parse_json_finds_object_in_answer(content):
    assert summarize.parse_json(content) == {"summary": "да"}


@pytest.mark.parametrize(
    "formula",
    [
        r"\frac{a}{b}",
        r"\theta + \tau",
        r"\nabla f",
        r"\left( x \right)",
        r"\beta \rho \underline{x}",
        r"\begin{pmatrix} 1 \end{pmatrix} \neq \textbf{v} \to \forall",
    ],
)
def test_parse_json_keeps_latex_commands(formula):
    content = '{"summary": "$' + formula + '$"}'

    assert summarize.parse_json(content) == {"summary": f"${formula}$"}


def test_parse_json_keeps_escaped_latex_and_json_escapes():
    content = r'{"summary": "$\\frac{1}{2}$\nПредел\n\nThe end\t\u00e9"}'

    assert summarize.parse_json(content) == {"summary": "$\\frac{1}{2}$\nПредел\n\nThe end\t\u00e9"}


@pytest.mark.parametrize(
    "text",
    [r"\nfor x in xs", r"\r\nsome text", r"\tif", r"\nthe end", r"\bold", r"\frame"],
)
def test_parse_json_keeps_json_escapes_before_lowercase_words(text):
    content = '{"summary": "' + text + '"}'

    assert summarize.parse_json(content) == json.loads(content)


@pytest.mark.parametrize("content", ["", "нет JSON", "[1, 2]", "} {"])
def test_parse_json_rejects_answer_without_object(content):
    with pytest.raises(ValueError):
        summarize.parse_json(content)


class RecordingLLM(ScriptedLLM):
    def __init__(self, reduce_answer: dict | None = None) -> None:
        super().__init__()
        self.systems: list[str] = []
        self.reduce_answer = reduce_answer

    async def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        self.systems.append(system)
        if self.reduce_answer is not None and "Главы" in system:
            return json.dumps(self.reduce_answer)
        return await super().complete(system, user, json_mode=json_mode)


@pytest.mark.parametrize(
    ("seconds", "min_count", "max_count", "max_seconds"),
    [
        (120, 1, 2, None),
        (180, 1, 3, None),
        (360, 3, 4, 300),
        (900, 3, 8, 300),
        (1200, 4, 10, 300),
        (3600, 4, 12, None),
        (7200, 8, 24, None),
    ],
)
def test_plan_chapters_depends_on_duration(seconds, min_count, max_count, max_seconds):
    plan = plan_chapters(seconds)

    assert (plan.min_count, plan.max_count, plan.max_seconds) == (
        min_count,
        max_count,
        max_seconds,
    )


def test_oversized_chapter_is_split_on_segment_boundaries():
    segments = make_segments([(m * 30.0, m * 30.0 + 29.0) for m in range(12)])
    chapters = [
        ChapterDraft("Всё подряд", 0, 359, "Кратко."),
    ]
    digests = [PartDigest(0, 359, "", [Topic("Начало", 0), Topic("Середина", 180)])]

    result = split_oversized(chapters, segments, digests, plan_chapters(360))

    assert len(result) >= 3
    assert result[0].start == 0
    assert result[-1].end == 359
    assert all(a.end == b.start for a, b in zip(result, result[1:], strict=False))
    assert all(c.end - c.start <= 300 for c in result)
    assert {c.start for c in result[1:]} <= {s.start for s in segments}
    assert len({c.title for c in result}) == len(result)


def test_split_keeps_good_chapters_untouched():
    segments = minute_segments(6)
    chapters = [
        ChapterDraft("Раз", 0, 120, "а"),
        ChapterDraft("Два", 120, 240, "б"),
        ChapterDraft("Три", 240, 359, "в"),
    ]

    assert split_oversized(chapters, segments, [], plan_chapters(359)) == chapters


def test_split_stops_when_no_boundaries_left():
    segments = make_segments([(0.0, 400.0)])
    chapters = [ChapterDraft("Одна", 0, 400, "")]

    assert split_oversized(chapters, segments, [], plan_chapters(400)) == chapters


async def test_short_lecture_gets_dense_chapters_and_parameterized_prompts(user, monkeypatch):
    llm = RecordingLLM(
        {
            "chapters": [{"title": "Всё", "start": 0, "summary": "Всё сразу."}],
            "summary_md": "## Итог",
        }
    )
    monkeypatch.setattr(summarize, "get_llm", lambda: llm)
    lecture = await create_transcribed_lecture(user, 6)

    await run_summarize(lecture.id)

    chapters, _ = await saved(lecture.id)
    assert len(chapters) >= 3
    assert all(c.end - c.start <= 300 for c in chapters)
    map_systems = [s for s in llm.systems if "фрагмент расшифровки" in s]
    assert len(map_systems) == 2
    assert all("{{" not in s for s in llm.systems)
    reduce_system = next(s for s in llm.systems if "Главы" in s)
    assert "5 мин 59 с" in reduce_system
    assert "от 3 до 4 глав" in reduce_system


async def test_long_lecture_keeps_part_size_and_hourly_range(user, monkeypatch):
    llm = RecordingLLM()
    monkeypatch.setattr(summarize, "get_llm", lambda: llm)
    lecture = await create_transcribed_lecture(user, 60)

    await run_summarize(lecture.id)

    assert len([s for s in llm.systems if "фрагмент расшифровки" in s]) == 4
    assert "от 4 до 12 глав" in next(s for s in llm.systems if "Главы" in s)


def test_repeated_split_keeps_titles_unique_and_fills_summary():
    segments = make_segments([(m * 30.0, m * 30.0 + 29.0) for m in range(24)])
    digests = [PartDigest(0, 719, "Описание части.", [])]
    chapters = [ChapterDraft("Тема", 0, 719, "Своё.")]

    result = split_oversized(chapters, segments, digests, plan_chapters(719))

    assert len(result) >= 3
    assert len({c.title for c in result}) == len(result)
    assert all(c.summary for c in result)
