import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import Lecture, LectureStatus, SourceType, StepStatus, TranscriptSegment, User
from app.pipeline.events import publish_status
from app.pipeline.runner import get_step
from app.pipeline.tasks import REGENERATION_STEPS, enqueue_regeneration
from app.services.consents import ai_transfer_given


@dataclass(frozen=True)
class DedupResult:
    lectures: int
    segments: int
    regenerated: list[uuid.UUID]


async def delete_duplicates(session: AsyncSession) -> list[uuid.UUID]:
    ranked = select(
        TranscriptSegment.id,
        func.row_number()
        .over(
            partition_by=(
                TranscriptSegment.lecture_id,
                TranscriptSegment.start,
                TranscriptSegment.end,
                TranscriptSegment.text,
            ),
            order_by=TranscriptSegment.id,
        )
        .label("rank"),
    ).subquery()
    deleted = await session.scalars(
        delete(TranscriptSegment)
        .where(TranscriptSegment.id.in_(select(ranked.c.id).where(ranked.c.rank > 1)))
        .returning(TranscriptSegment.lecture_id)
    )
    return list(deleted)


async def renumber(session: AsyncSession, lecture_ids: list[uuid.UUID]) -> None:
    numbered = (
        select(
            TranscriptSegment.id,
            (
                func.row_number().over(
                    partition_by=TranscriptSegment.lecture_id,
                    order_by=(TranscriptSegment.idx, TranscriptSegment.id),
                )
                - 1
            ).label("position"),
        )
        .where(TranscriptSegment.lecture_id.in_(lecture_ids))
        .subquery()
    )
    await session.execute(
        update(TranscriptSegment)
        .where(TranscriptSegment.id == numbered.c.id)
        .values(idx=numbered.c.position)
        .execution_options(synchronize_session=False)
    )


async def mark_for_regeneration(
    session: AsyncSession, lecture_ids: list[uuid.UUID]
) -> list[Lecture]:
    rows = await session.execute(
        select(Lecture, User.ai_transfer_accepted_at, User.ai_transfer_revision)
        .join(User, User.id == Lecture.owner_id)
        .where(
            Lecture.id.in_(lecture_ids),
            Lecture.status == LectureStatus.ready,
            Lecture.source_type != SourceType.local,
            Lecture.processed_locally.is_(False),
        )
        .order_by(Lecture.id)
        .with_for_update(of=Lecture)
    )
    lectures = []
    for lecture, accepted_at, revision in rows:
        if not ai_transfer_given(accepted_at, revision):
            continue
        for name in REGENERATION_STEPS:
            step = await get_step(session, lecture.id, name)
            step.status = StepStatus.pending
            step.progress = 0.0
            step.stage = None
            step.error = None
        lecture.status = LectureStatus.processing
        lectures.append(lecture)
    return lectures


async def dedup_segments() -> DedupResult:
    async with SessionLocal() as session:
        deleted = await delete_duplicates(session)
        lecture_ids = sorted(set(deleted))
        if not lecture_ids:
            return DedupResult(lectures=0, segments=0, regenerated=[])
        await renumber(session, lecture_ids)
        lectures = await mark_for_regeneration(session, lecture_ids)
        await session.commit()
    for lecture in lectures:
        await publish_status(lecture.id, lecture.owner_id, LectureStatus.processing)
        await enqueue_regeneration(lecture.id)
    return DedupResult(
        lectures=len(lecture_ids),
        segments=len(deleted),
        regenerated=[lecture.id for lecture in lectures],
    )


if __name__ == "__main__":
    result = asyncio.run(dedup_segments())
    print(f"Лекций с дублями: {result.lectures}")
    print(f"Удалено сегментов: {result.segments}")
    print(f"Поставлено на пересоздание глав, конспекта и поиска: {len(result.regenerated)}")
