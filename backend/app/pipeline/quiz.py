import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chapter, Lecture, Quiz, TranscriptSegment
from app.pipeline.runner import Report
from app.pipeline.stages import load_segments, require_ai_transfer
from app.pipeline.summarize import (
    format_part,
    load_prompt,
    parse_json,
    parse_start,
    split_into_parts,
)
from app.providers import LLM, get_llm
from app.schemas.lecture import QuizQuestion

MIN_QUESTIONS = 8
MAX_QUESTIONS = 12
MIN_OPTIONS = 2
MAX_OPTIONS = 6
QUIZ_ATTEMPTS = 3
TRANSCRIPT_CHAR_LIMIT = 60_000


class InvalidQuiz(ValueError):
    pass


def transcript_excerpt(
    segments: list[TranscriptSegment], limit: int = TRANSCRIPT_CHAR_LIMIT
) -> str:
    full = format_part(segments)
    if len(full) <= limit:
        return full
    parts = split_into_parts(segments)
    budget = limit // len(parts)
    excerpts = []
    for part in parts:
        lines: list[str] = []
        used = 0
        for segment in part:
            line = format_part([segment])
            if lines and used + len(line) > budget:
                break
            lines.append(line)
            used += len(line) + 1
        excerpts.append("\n".join(lines))
    return "\n…\n".join(excerpts)


def quiz_request(
    lecture: Lecture, chapters: list[Chapter], segments: list[TranscriptSegment]
) -> str:
    return json.dumps(
        {
            "title": lecture.title,
            "chapters": [
                {
                    "title": chapter.title,
                    "start": int(chapter.start),
                    "end": int(chapter.end),
                    "summary": chapter.summary,
                }
                for chapter in chapters
            ],
            "transcript": transcript_excerpt(segments),
        },
        ensure_ascii=False,
    )


def parse_question(item: Any, lecture_end: float) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise InvalidQuiz("вопрос не в формате объекта")
    question = str(item.get("question") or "").strip()
    if not question:
        raise InvalidQuiz("у вопроса нет текста")
    raw_options = item.get("options")
    if not isinstance(raw_options, list) or not MIN_OPTIONS <= len(raw_options) <= MAX_OPTIONS:
        raise InvalidQuiz(f"у вопроса должно быть от {MIN_OPTIONS} до {MAX_OPTIONS} вариантов")
    options = [str(option).strip() for option in raw_options]
    if not all(options) or len(set(options)) != len(options):
        raise InvalidQuiz("варианты ответа пустые или повторяются")
    correct_index = item.get("correct_index")
    if (
        isinstance(correct_index, bool)
        or not isinstance(correct_index, int)
        or not 0 <= correct_index < len(options)
    ):
        raise InvalidQuiz("correct_index не указывает на вариант ответа")
    timestamp = parse_start(item.get("timestamp"))
    if timestamp is None or not 0 <= timestamp <= lecture_end:
        raise InvalidQuiz("таймкод вопроса вне лекции")
    return QuizQuestion(
        question=question,
        options=options,
        correct_index=correct_index,
        explanation=str(item.get("explanation") or "").strip(),
        timestamp=timestamp,
    ).model_dump()


def parse_questions(content: str, lecture_end: float) -> list[dict[str, Any]]:
    items = parse_json(content).get("questions")
    if not isinstance(items, list) or not MIN_QUESTIONS <= len(items) <= MAX_QUESTIONS:
        raise InvalidQuiz(f"в квизе должно быть от {MIN_QUESTIONS} до {MAX_QUESTIONS} вопросов")
    return [parse_question(item, lecture_end) for item in items]


async def generate_questions(
    llm: LLM, request: str, lecture_end: float, report: Report
) -> list[dict[str, Any]]:
    reason = ""
    for attempt in range(1, QUIZ_ATTEMPTS + 1):
        content = await llm.complete(load_prompt("quiz"), request, json_mode=True)
        try:
            return parse_questions(content, lecture_end)
        except ValueError as error:
            reason = str(error)
        await report(attempt / QUIZ_ATTEMPTS)
    raise InvalidQuiz(f"Не удалось собрать квиз: {reason}")


async def build_quiz(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    await require_ai_transfer(session, lecture)
    segments = await load_segments(session, lecture)
    if not segments:
        raise InvalidQuiz("В лекции нет расшифровки, квиз собрать не из чего")
    chapters = await session.scalars(
        select(Chapter).where(Chapter.lecture_id == lecture.id).order_by(Chapter.idx)
    )
    lecture_end = lecture.duration_sec or segments[-1].end
    questions = await generate_questions(
        get_llm(), quiz_request(lecture, list(chapters), segments), lecture_end, report
    )
    await session.execute(
        insert(Quiz)
        .values(lecture_id=lecture.id, questions=questions)
        .on_conflict_do_update(
            index_elements=[Quiz.lecture_id],
            set_={"questions": questions, "created_at": func.now()},
        )
    )
