from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lecture, TranscriptSegment
from app.pipeline.runner import Report
from app.providers import get_speech_to_text
from app.services.quota import QuotaExceeded, charge_lecture


async def transcribe(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    segments = await get_speech_to_text().transcribe(
        Path(lecture.audio_path or ""), lecture.language
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
