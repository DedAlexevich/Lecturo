import json
import uuid
from dataclasses import dataclass
from typing import Any

from arq import create_pool
from arq.jobs import Job, JobStatus
from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.redis import get_redis
from app.models import Course, ExamSheet, Lecture, Summary, User, course_lectures
from app.pipeline.jobs import queue_settings
from app.pipeline.summarize import MAP_ATTEMPTS, complete_json, load_prompt
from app.pipeline.tasks import enqueue
from app.providers import LLM, get_llm
from app.services.consents import ai_transfer_given


@dataclass(frozen=True)
class LectureNotes:
    lecture_id: uuid.UUID
    title: str
    content_md: str


@dataclass(frozen=True)
class LectureDigest:
    title: str
    tickets: list[str]
    definitions: list[dict[str, str]]
    cheatsheet_md: str


@dataclass(frozen=True)
class ExamSheetDraft:
    tickets: list[str]
    definitions: list[dict[str, str]]
    cheatsheet_md: str


def with_course_notes(query: Select, course_id: uuid.UUID) -> Select:
    return (
        query.join(course_lectures, course_lectures.c.lecture_id == Lecture.id)
        .join(Summary, Summary.lecture_id == Lecture.id)
        .where(course_lectures.c.course_id == course_id, Summary.content_md != "")
    )


async def load_course_notes(session: AsyncSession, course_id: uuid.UUID) -> list[LectureNotes]:
    rows = await session.execute(
        with_course_notes(
            select(Lecture.id, Lecture.title, Summary.content_md), course_id
        ).order_by(course_lectures.c.position, course_lectures.c.added_at)
    )
    return [
        LectureNotes(lecture_id=lecture_id, title=title, content_md=content)
        for lecture_id, title, content in rows
    ]


async def course_note_ids(session: AsyncSession, course_id: uuid.UUID) -> set[uuid.UUID]:
    return set(await session.scalars(with_course_notes(select(Lecture.id), course_id)))


def is_outdated(content: dict, lecture_ids: set[uuid.UUID]) -> bool:
    built_from = content.get("lecture_ids")
    return built_from is None or set(built_from) != {str(item) for item in lecture_ids}


def parse_tickets(items: Any) -> list[str]:
    tickets: list[str] = []
    for item in items if isinstance(items, list) else []:
        ticket = str(item).strip() if isinstance(item, str | int | float) else ""
        if ticket and ticket not in tickets:
            tickets.append(ticket)
    return tickets


def parse_definitions(items: Any) -> list[dict[str, str]]:
    definitions: dict[str, dict[str, str]] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        definition = str(item.get("definition") or "").strip()
        known = definitions.get(term.casefold())
        if term and definition and (known is None or len(definition) > len(known["definition"])):
            definitions[term.casefold()] = {"term": term, "definition": definition}
    return list(definitions.values())


def outline(content_md: str) -> str:
    return "\n".join(
        f"- {line.lstrip('#').strip()}" for line in content_md.splitlines() if line.startswith("#")
    )


async def digest_lecture(llm: LLM, notes: LectureNotes) -> LectureDigest:
    request = f"# {notes.title}\n\n{notes.content_md}"
    data = await complete_json(llm, load_prompt("exam_map"), request, MAP_ATTEMPTS)
    return LectureDigest(
        title=notes.title,
        tickets=parse_tickets(data.get("tickets")),
        definitions=parse_definitions(data.get("definitions")),
        cheatsheet_md=str(data.get("cheatsheet_md") or "").strip() or outline(notes.content_md),
    )


def exam_reduce_request(course_title: str, digests: list[LectureDigest]) -> str:
    lectures = [
        {
            "title": digest.title,
            "tickets": digest.tickets,
            "definitions": digest.definitions,
            "cheatsheet_md": digest.cheatsheet_md,
        }
        for digest in digests
    ]
    return json.dumps({"course": course_title, "lectures": lectures}, ensure_ascii=False)


def merge_digests(data: dict[str, Any], digests: list[LectureDigest]) -> ExamSheetDraft:
    tickets = parse_tickets(data.get("tickets")) or parse_tickets(
        [ticket for digest in digests for ticket in digest.tickets]
    )
    definitions = parse_definitions(data.get("definitions")) or parse_definitions(
        [definition for digest in digests for definition in digest.definitions]
    )
    cheatsheet = str(data.get("cheatsheet_md") or "").strip() or "\n\n".join(
        f"## {digest.title}\n\n{digest.cheatsheet_md}" for digest in digests
    )
    return ExamSheetDraft(tickets=tickets, definitions=definitions, cheatsheet_md=cheatsheet)


async def compose_exam_sheet(
    llm: LLM, course_title: str, notes: list[LectureNotes]
) -> ExamSheetDraft:
    digests = [await digest_lecture(llm, lecture) for lecture in notes]
    request = exam_reduce_request(course_title, digests)
    data = await complete_json(llm, load_prompt("exam_reduce"), request, MAP_ATTEMPTS)
    return merge_digests(data, digests)


async def save_exam_sheet(
    session: AsyncSession,
    course_id: uuid.UUID,
    draft: ExamSheetDraft,
    lecture_ids: list[uuid.UUID],
) -> None:
    content = {
        "tickets": draft.tickets,
        "definitions": draft.definitions,
        "cheatsheet_md": draft.cheatsheet_md,
        "lecture_ids": [str(lecture_id) for lecture_id in lecture_ids],
    }
    await session.execute(
        insert(ExamSheet)
        .values(course_id=course_id, content=content)
        .on_conflict_do_update(index_elements=[ExamSheet.course_id], set_={"content": content})
    )


async def build_exam_sheet(ctx: dict, course_id: str) -> str:
    course_uuid = uuid.UUID(course_id)
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(Course.title, User.ai_transfer_accepted_at, User.ai_transfer_revision)
                .join(User, User.id == Course.owner_id)
                .where(Course.id == course_uuid)
            )
        ).one_or_none()
        if row is None:
            return "missing"
        course_title, accepted_at, revision = row
        if not ai_transfer_given(accepted_at, revision):
            return "no_consent"
        notes = await load_course_notes(session, course_uuid)
        if not notes:
            return "empty"
        try:
            draft = await compose_exam_sheet(get_llm(), course_title, notes)
            await save_exam_sheet(
                session, course_uuid, draft, [lecture.lecture_id for lecture in notes]
            )
            await session.commit()
        except Exception:
            await mark_exam_sheet_failed(course_uuid)
            raise
        return "ready"


def exam_sheet_failure_key(course_id: uuid.UUID) -> str:
    return f"exam-sheet-failed:{course_id}"


async def mark_exam_sheet_failed(course_id: uuid.UUID) -> None:
    settings = get_settings()
    await get_redis(settings.redis_url).set(
        exam_sheet_failure_key(course_id), "1", ex=settings.exam_sheet_failure_ttl_seconds
    )


async def clear_exam_sheet_failure(course_id: uuid.UUID) -> None:
    await get_redis(get_settings().redis_url).delete(exam_sheet_failure_key(course_id))


async def exam_sheet_failed(course_id: uuid.UUID) -> bool:
    return bool(await get_redis(get_settings().redis_url).exists(exam_sheet_failure_key(course_id)))


def exam_sheet_job_id(course_id: uuid.UUID) -> str:
    return f"exam-sheet:{course_id}"


async def enqueue_exam_sheet(course_id: uuid.UUID) -> None:
    await enqueue("build_exam_sheet", exam_sheet_job_id(course_id), str(course_id))


async def exam_sheet_in_progress(course_id: uuid.UUID) -> bool:
    redis = await create_pool(queue_settings())
    try:
        job = Job(exam_sheet_job_id(course_id), redis)
        return await job.status() in (JobStatus.deferred, JobStatus.queued, JobStatus.in_progress)
    finally:
        await redis.aclose()
