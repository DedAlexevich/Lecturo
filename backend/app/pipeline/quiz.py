import json
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chapter, Lecture, Quiz, TranscriptSegment
from app.pipeline.runner import Report, UserFacingError
from app.pipeline.stages import load_segments, require_ai_transfer
from app.pipeline.summarize import (
    escape_latex,
    format_part,
    load_prompt,
    parse_json,
    parse_start,
    split_into_parts,
)
from app.pipeline.timecodes import locate_timestamp
from app.providers import LLM, get_llm
from app.providers.openai_compat import OpenAICompatibleError, OpenAICompatibleTruncated
from app.schemas.lecture import QuizQuestion

MIN_QUESTIONS = 6
MAX_QUESTIONS = 12
MIN_OPTIONS = 2
MAX_OPTIONS = 6
QUIZ_ATTEMPTS = 3
QUIZ_MAX_TOKENS = 6144
COMPACT_QUIZ_NOTE = (
    "\n\nОтвет должен быть короче: ровно 6 вопросов, объяснение в одно короткое предложение, "
    "evidence из 5–10 слов."
)
TRANSCRIPT_CHAR_LIMIT = 60_000

logger = logging.getLogger(__name__)


class InvalidQuiz(UserFacingError, ValueError):
    pass


def spread_lines(lines: list[str], budget: int) -> list[str]:
    last = len(lines) - 1
    count = len(lines)
    while count > 1:
        picked = [lines[round(index * last / (count - 1))] for index in range(count)]
        if sum(len(line) + 1 for line in picked) <= budget:
            return picked
        count -= 1
    return lines[:1]


def transcript_excerpt(
    segments: list[TranscriptSegment], limit: int = TRANSCRIPT_CHAR_LIMIT
) -> str:
    full = format_part(segments)
    if len(full) <= limit:
        return full
    parts = split_into_parts(segments)
    budget = limit // len(parts)
    return "\n…\n".join(
        "\n".join(spread_lines([format_part([segment]) for segment in part], budget))
        for part in parts
    )


def quiz_request(
    lecture: Lecture,
    chapters: list[Chapter],
    segments: list[TranscriptSegment],
    limit: int = TRANSCRIPT_CHAR_LIMIT,
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
            "transcript": transcript_excerpt(segments, limit),
        },
        ensure_ascii=False,
    )


def parse_question(
    item: Any, segments: list[TranscriptSegment], lecture_end: float
) -> dict[str, Any]:
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
    explanation = str(item.get("explanation") or "").strip()
    hint = parse_start(item.get("timestamp"))
    if hint is not None and not 0 <= hint <= lecture_end:
        hint = None
    timestamp = locate_timestamp(
        segments, str(item.get("evidence") or ""), question, explanation, hint
    )
    if timestamp is None:
        raise InvalidQuiz("не удалось определить таймкод вопроса")
    return QuizQuestion(
        question=question,
        options=options,
        correct_index=correct_index,
        explanation=explanation,
        timestamp=timestamp,
    ).model_dump()


def valid_questions(
    items: Any, segments: list[TranscriptSegment], lecture_end: float
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise InvalidQuiz("в ответе нет списка вопросов")
    questions = []
    reasons = []
    for item in items:
        try:
            questions.append(parse_question(item, segments, lecture_end))
        except InvalidQuiz as error:
            reasons.append(str(error))
    if reasons:
        logger.warning("Отброшено вопросов квиза: %s (%s)", len(reasons), "; ".join(reasons))
    if len(questions) < MIN_QUESTIONS:
        details = f": {reasons[0]}" if reasons else ""
        raise InvalidQuiz(
            f"в квизе {len(questions)} корректных вопросов, нужно хотя бы {MIN_QUESTIONS}" + details
        )
    return questions[:MAX_QUESTIONS]


def parse_questions(
    content: str, segments: list[TranscriptSegment], lecture_end: float
) -> list[dict[str, Any]]:
    return valid_questions(parse_json(content).get("questions"), segments, lecture_end)


def finished_items(content: str) -> list[Any]:
    key = content.find('"questions"')
    start = content.find("[", key) if key >= 0 else -1
    if start < 0:
        return []
    text = escape_latex(content[start + 1 :])
    decoder = json.JSONDecoder()
    items: list[Any] = []
    position = 0
    while True:
        while position < len(text) and text[position] in " \t\r\n,":
            position += 1
        if position >= len(text) or text[position] == "]":
            return items
        try:
            item, position = decoder.raw_decode(text, position)
        except ValueError:
            return items
        items.append(item)


def rescue_questions(
    content: str, segments: list[TranscriptSegment], lecture_end: float
) -> list[dict[str, Any]] | None:
    try:
        return valid_questions(finished_items(content), segments, lecture_end)
    except InvalidQuiz:
        return None


async def generate_questions(
    llm: LLM,
    full_request: str,
    compact_request: str,
    segments: list[TranscriptSegment],
    lecture_end: float,
    report: Report,
) -> list[dict[str, Any]]:
    failure: Exception = InvalidQuiz("Не удалось собрать квиз")
    compact = False
    for attempt in range(1, QUIZ_ATTEMPTS + 1):
        system = load_prompt("quiz") + (COMPACT_QUIZ_NOTE if compact else "")
        request = compact_request if compact else full_request
        try:
            content = await llm.complete(
                system, request, json_mode=True, max_tokens=QUIZ_MAX_TOKENS
            )
        except OpenAICompatibleTruncated as error:
            rescued = rescue_questions(error.content, segments, lecture_end)
            if rescued is not None:
                logger.warning("Ответ с квизом обрезан, взято готовых вопросов: %s", len(rescued))
                return rescued
            logger.warning("Ответ с квизом обрезан, запрос сокращён")
            compact = True
            failure = error
        except OpenAICompatibleError as error:
            logger.warning("Запрос квиза не удался: %s", error)
            failure = error
        else:
            try:
                return parse_questions(content, segments, lecture_end)
            except ValueError as error:
                failure = InvalidQuiz(f"Не удалось собрать квиз: {error}")
        await report(attempt / QUIZ_ATTEMPTS)
    raise failure


async def build_quiz(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    await require_ai_transfer(session, lecture)
    segments = await load_segments(session, lecture)
    if not segments:
        raise InvalidQuiz("В лекции нет расшифровки, квиз собрать не из чего")
    chapters = await session.scalars(
        select(Chapter).where(Chapter.lecture_id == lecture.id).order_by(Chapter.idx)
    )
    lecture_end = lecture.duration_sec or segments[-1].end
    chapter_list = list(chapters)
    full_request = quiz_request(lecture, chapter_list, segments)
    compact_request = quiz_request(lecture, chapter_list, segments, TRANSCRIPT_CHAR_LIMIT // 2)
    await session.commit()
    questions = await generate_questions(
        get_llm(), full_request, compact_request, segments, lecture_end, report
    )
    await session.execute(
        insert(Quiz)
        .values(lecture_id=lecture.id, questions=questions)
        .on_conflict_do_update(
            index_elements=[Quiz.lecture_id],
            set_={"questions": questions, "created_at": func.now()},
        )
    )
