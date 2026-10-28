import asyncio
import uuid
from pathlib import Path

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import Lecture, ProcessingStep, StepName, TranscriptSegment, User
from app.pipeline.media import probe_duration
from app.pipeline.runner import Report, UserFacingError, get_step
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


class StepOperations:
    def __init__(self, session: AsyncSession, step: ProcessingStep, lock: asyncio.Lock) -> None:
        self.session = session
        self.step = step
        self.lock = lock

    def _all(self) -> dict[str, dict[str, str]]:
        return dict((self.step.external or {}).get("operations", {}))

    async def load(self, name: str) -> dict[str, str] | None:
        return self._all().get(name)

    async def save(self, name: str, state: dict[str, str]) -> None:
        async with self.lock:
            operations = self._all()
            operations[name] = state
            await self._write(operations)

    async def drop(self, name: str) -> None:
        async with self.lock:
            operations = self._all()
            operations.pop(name, None)
            await self._write(operations)

    async def alive(self) -> bool:
        async with SessionLocal() as session:
            return bool(
                await session.scalar(select(exists().where(ProcessingStep.id == self.step.id)))
            )

    async def _write(self, operations: dict[str, dict[str, str]]) -> None:
        self.step.external = {"operations": operations} if operations else None
        await self.session.commit()


async def transcribe(session: AsyncSession, lecture: Lecture, report: Report) -> None:
    await require_ai_transfer(session, lecture)
    audio_path = Path(lecture.audio_path or "")
    if lecture.duration_sec is None:
        lecture.duration_sec = await probe_duration(audio_path)
    if not await charge_lecture(session, lecture.owner_id, lecture.id, lecture.duration_sec):
        raise QuotaExceeded("Не хватает лимита на обработку лекции")
    await session.commit()

    step = await get_step(session, lecture.id, StepName.transcribe)
    await session.commit()
    lock = asyncio.Lock()

    async def on_progress(stage: str, fraction: float) -> None:
        async with lock:
            await report(fraction, stage)

    stt = get_speech_to_text()
    segments = await stt.transcribe(
        audio_path,
        lecture.language,
        duration=lecture.duration_sec,
        on_progress=on_progress,
        operations=StepOperations(session, step, lock),
    )
    await session.execute(
        delete(TranscriptSegment).where(TranscriptSegment.lecture_id == lecture.id)
    )
    session.add_all(
        TranscriptSegment(lecture_id=lecture.id, idx=idx, start=s.start, end=s.end, text=s.text)
        for idx, s in enumerate(segments)
    )
    await stt.discard(object_keys(step.external))
    step.external = None


def object_keys(external: dict | None) -> list[str]:
    operations = (external or {}).get("operations", {})
    return [state["object_key"] for state in operations.values() if state.get("object_key")]


async def lock_operation_objects(session: AsyncSession, lecture_ids: list[uuid.UUID]) -> list[str]:
    rows = await session.scalars(
        select(ProcessingStep.external)
        .where(
            ProcessingStep.lecture_id.in_(lecture_ids),
            ProcessingStep.step == StepName.transcribe,
        )
        .with_for_update()
    )
    return [key for external in rows for key in object_keys(external)]


async def discard_operation_objects(object_keys: list[str]) -> None:
    if object_keys:
        await get_speech_to_text().discard(object_keys)


async def load_segments(session: AsyncSession, lecture: Lecture) -> list[TranscriptSegment]:
    rows = await session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.lecture_id == lecture.id)
        .order_by(TranscriptSegment.idx)
    )
    return list(rows)
