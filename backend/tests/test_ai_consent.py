from datetime import date

import pytest
from sqlalchemy import func, select, update

from app.core.db import SessionLocal
from app.models import (
    Lecture,
    LectureStatus,
    ProcessingStep,
    SearchChunk,
    SourceType,
    StepName,
    StepStatus,
    TranscriptSegment,
    User,
)
from app.pipeline import embed, stages, summarize, tasks


async def revoke_consent(user: User) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(ai_transfer_accepted_at=None, ai_transfer_revision=None)
        )
        await session.commit()


async def create_link_lecture(user: User) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Матанализ",
            source_type=SourceType.link,
            duration_sec=2.0,
            audio_path="missing.opus",
        )
        session.add(lecture)
        await session.commit()
        return lecture


async def create_local_lecture(user: User) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Линейная алгебра",
            source_type=SourceType.local,
            duration_sec=20.0,
            processed_locally=True,
        )
        session.add(lecture)
        await session.flush()
        session.add_all(
            TranscriptSegment(
                lecture_id=lecture.id, idx=idx, start=start, end=start + 9.0, text=text
            )
            for idx, (start, text) in enumerate([(0.0, "Матрицы"), (10.0, "Определители")])
        )
        await session.commit()
        return lecture


class ForbiddenEmbeddings:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("Текст ушёл провайдеру эмбеддингов")


async def noop_download(session, lecture, report) -> None:
    return None


async def report(progress: float) -> None:
    return None


async def test_transcribe_requires_consent(user):
    await revoke_consent(user)
    lecture = await create_link_lecture(user)
    async with SessionLocal() as session:
        stored = await session.get(Lecture, lecture.id)
        with pytest.raises(stages.ConsentMissing):
            await stages.transcribe(session, stored, report)


async def test_summarize_requires_consent(user):
    await revoke_consent(user)
    lecture = await create_link_lecture(user)
    async with SessionLocal() as session:
        stored = await session.get(Lecture, lecture.id)
        with pytest.raises(stages.ConsentMissing):
            await summarize.summarize(session, stored, report)


async def test_pipeline_without_consent_fails_before_server_processing(user, monkeypatch):
    monkeypatch.setitem(tasks.HANDLERS, StepName.download, noop_download)
    await revoke_consent(user)
    lecture = await create_link_lecture(user)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.failed

    async with SessionLocal() as session:
        step = await session.scalar(
            select(ProcessingStep).where(
                ProcessingStep.lecture_id == lecture.id, ProcessingStep.step == StepName.transcribe
            )
        )
        assert step.status == StepStatus.failed
        assert step.error == stages.AI_TRANSFER_REQUIRED
        segments = await session.scalar(
            select(func.count())
            .select_from(TranscriptSegment)
            .where(TranscriptSegment.lecture_id == lecture.id)
        )
        assert segments == 0


async def test_embed_requires_consent(user, monkeypatch):
    monkeypatch.setattr(embed, "get_embeddings", ForbiddenEmbeddings)
    await revoke_consent(user)
    lecture = await create_local_lecture(user)
    async with SessionLocal() as session:
        stored = await session.get(Lecture, lecture.id)
        with pytest.raises(stages.ConsentMissing):
            await embed.embed(session, stored, report)


async def test_local_lecture_with_consent_is_embedded(user):
    lecture = await create_local_lecture(user)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    async with SessionLocal() as session:
        chunks = await session.scalar(
            select(func.count())
            .select_from(SearchChunk)
            .where(SearchChunk.lecture_id == lecture.id)
        )
        assert chunks == 1


async def test_local_lecture_without_consent_is_not_embedded(user, monkeypatch):
    monkeypatch.setattr(embed, "get_embeddings", ForbiddenEmbeddings)
    await revoke_consent(user)
    lecture = await create_local_lecture(user)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.failed

    async with SessionLocal() as session:
        step = await session.scalar(
            select(ProcessingStep).where(
                ProcessingStep.lecture_id == lecture.id, ProcessingStep.step == StepName.embed
            )
        )
        assert step.status == StepStatus.failed
        assert step.error == stages.AI_TRANSFER_REQUIRED
        chunks = await session.scalar(
            select(func.count())
            .select_from(SearchChunk)
            .where(SearchChunk.lecture_id == lecture.id)
        )
        assert chunks == 0


async def test_outdated_revision_blocks_server_processing(user):
    async with SessionLocal() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(ai_transfer_revision=date(2020, 1, 1))
        )
        await session.commit()
    lecture = await create_link_lecture(user)
    async with SessionLocal() as session:
        stored = await session.get(Lecture, lecture.id)
        with pytest.raises(stages.ConsentMissing):
            await stages.transcribe(session, stored, report)
