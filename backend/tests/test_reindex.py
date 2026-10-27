from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Lecture, SearchChunk, SourceType
from app.pipeline.reindex import reindex_embeddings


async def test_reindex_fills_only_missing_embeddings(user):
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=user.id, title="Лекция", source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        session.add_all(
            [
                SearchChunk(lecture_id=lecture.id, start=0, end=30, text="первый", embedding=None),
                SearchChunk(lecture_id=lecture.id, start=30, end=60, text="второй", embedding=None),
                SearchChunk(
                    lecture_id=lecture.id, start=60, end=90, text="третий", embedding=[0.1] * 256
                ),
            ]
        )
        await session.commit()
        lecture_id = lecture.id

    assert await reindex_embeddings() >= 2

    async with SessionLocal() as session:
        chunks = list(
            await session.scalars(select(SearchChunk).where(SearchChunk.lecture_id == lecture_id))
        )
    assert len(chunks) == 3
    assert all(chunk.embedding is not None for chunk in chunks)
