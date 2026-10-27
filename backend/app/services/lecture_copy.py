import uuid

from sqlalchemy import Uuid, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chapter,
    Course,
    Lecture,
    LectureStatus,
    SearchChunk,
    SourceType,
    Summary,
    TranscriptSegment,
    course_lectures,
)


async def existing_copy_id(
    session: AsyncSession, owner_id: uuid.UUID, source_id: uuid.UUID
) -> uuid.UUID | None:
    return await session.scalar(
        select(Lecture.id).where(Lecture.owner_id == owner_id, Lecture.copied_from_id == source_id)
    )


async def existing_course_copy_id(
    session: AsyncSession, owner_id: uuid.UUID, source_id: uuid.UUID
) -> uuid.UUID | None:
    return await session.scalar(
        select(Course.id).where(Course.owner_id == owner_id, Course.copied_from_id == source_id)
    )


async def copy_lecture(session: AsyncSession, source: Lecture, owner_id: uuid.UUID) -> uuid.UUID:
    keeps_source = source.source_type == SourceType.link
    copy = Lecture(
        owner_id=owner_id,
        title=source.title,
        source_type=source.source_type,
        source_url=source.source_url if keeps_source else None,
        embed_url=source.embed_url if keeps_source else None,
        duration_sec=source.duration_sec,
        language=source.language,
        status=LectureStatus.ready,
        processed_locally=source.processed_locally,
        copied_from_id=source.id,
    )
    session.add(copy)
    await session.flush()
    target = literal(copy.id, Uuid())

    await session.execute(
        insert(TranscriptSegment).from_select(
            ["lecture_id", "idx", "start", "end", "text"],
            select(
                target,
                TranscriptSegment.idx,
                TranscriptSegment.start,
                TranscriptSegment.end,
                TranscriptSegment.text,
            ).where(TranscriptSegment.lecture_id == source.id),
        )
    )
    await session.execute(
        insert(Chapter).from_select(
            ["lecture_id", "idx", "start", "end", "title", "summary"],
            select(
                target,
                Chapter.idx,
                Chapter.start,
                Chapter.end,
                Chapter.title,
                Chapter.summary,
            ).where(Chapter.lecture_id == source.id),
        )
    )
    await session.execute(
        insert(Summary).from_select(
            ["lecture_id", "content_md"],
            select(target, Summary.content_md).where(Summary.lecture_id == source.id),
        )
    )
    await session.execute(
        insert(SearchChunk).from_select(
            ["lecture_id", "kind", "start", "end", "section", "text", "embedding"],
            select(
                target,
                SearchChunk.kind,
                SearchChunk.start,
                SearchChunk.end,
                SearchChunk.section,
                SearchChunk.text,
                SearchChunk.embedding,
            ).where(SearchChunk.lecture_id == source.id),
        )
    )
    return copy.id


async def copy_course(
    session: AsyncSession, source: Course, lectures: list[Lecture], owner_id: uuid.UUID
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    copy = Course(
        owner_id=owner_id,
        title=source.title,
        description=source.description,
        copied_from_id=source.id,
    )
    session.add(copy)
    await session.flush()
    lecture_ids: list[uuid.UUID] = []
    for position, lecture in enumerate(lectures):
        lecture_id = await existing_copy_id(session, owner_id, lecture.id)
        if lecture_id is None:
            lecture_id = await copy_lecture(session, lecture, owner_id)
        lecture_ids.append(lecture_id)
        await session.execute(
            insert(course_lectures).values(
                course_id=copy.id, lecture_id=lecture_id, position=position
            )
        )
    return copy.id, lecture_ids
