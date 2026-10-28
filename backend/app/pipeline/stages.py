from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lecture, TranscriptSegment, User
from app.pipeline.runner import Report, UserFacingError
from app.providers import get_speech_to_text
from app.services.consents import AI_TRANSFER_REQUIRED, ai_transfer_given
from app.services.quota import QuotaExceeded, charge_lecture


class ConsentMissing(UserFacingError):
    pass


async def require_ai_transfer(session: AsyncSession, lecture: Lecture) -> None:
    row = (
        await session.execute(
            select(User.ai_transfer_accepted_at, User.ai_transfer_revision).where(
                User.id == lecture.owner_id
            )
        )
    ).one_or_none()
    if row is None or not ai_transfer_given(*row):
        raise ConsentMissing(AI_TRANSFER_REQUIRED)


async def transcribe(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    await require_ai_transfer(session, lecture)

    async def on_progress(stage: str, fraction: float) -> None:
        await report(fraction, stage)

    segments = await get_speech_to_text().transcribe(
        Path(lecture.audio_path or ""),
        lecture.language,
        duration=lecture.duration_sec,
        on_progress=on_progress,
    )
    await session.execute(
        delete(TranscriptSegment).where(TranscriptSegment.lecture_id == lecture.id)
    )
    session.add_all(
        TranscriptSegment(lecture_id=lecture.id, idx=idx, start=s.start, end=s.end, text=s.text)
        for idx, s in enumerate(segments)
    )
    if lecture.duration_sec is None and segments:
        lecture.duration_sec = segments[-1].end
    if not await charge_lecture(session, lecture.owner_id, lecture.id, lecture.duration_sec or 0.0):
        raise QuotaExceeded("Не хватает лимита на обработку лекции")


async def load_segments(session: AsyncSession, lecture: Lecture) -> list[TranscriptSegment]:
    rows = await session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.lecture_id == lecture.id)
        .order_by(TranscriptSegment.idx)
    )
    return list(rows)
