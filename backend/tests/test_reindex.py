import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Lecture, SearchChunk, SourceType, User
from app.pipeline import reindex
from app.pipeline.reindex import reindex_embeddings
from app.providers.openai_compat import OpenAICompatibleError
from app.providers.stub import StubEmbeddings


async def add_lecture(owner_id, *texts: str, with_vector: str | None = None):
    async with SessionLocal() as session:
        lecture = Lecture(owner_id=owner_id, title="Лекция", source_type=SourceType.upload)
        session.add(lecture)
        await session.flush()
        session.add_all(
            SearchChunk(lecture_id=lecture.id, start=idx * 30, end=idx * 30 + 30, text=text)
            for idx, text in enumerate(texts)
        )
        if with_vector:
            session.add(
                SearchChunk(
                    lecture_id=lecture.id,
                    start=300,
                    end=330,
                    text=with_vector,
                    embedding=[0.1] * 256,
                )
            )
        await session.commit()
        return lecture.id


async def load_chunks(lecture_id):
    async with SessionLocal() as session:
        return list(
            await session.scalars(select(SearchChunk).where(SearchChunk.lecture_id == lecture_id))
        )


async def test_reindex_fills_only_missing_embeddings(user):
    lecture_id = await add_lecture(user.id, "первый", "второй", with_vector="третий")

    assert await reindex_embeddings() >= 2

    chunks = await load_chunks(lecture_id)
    assert len(chunks) == 3
    assert all(chunk.embedding is not None for chunk in chunks)
    kept = next(chunk for chunk in chunks if chunk.text == "третий")
    assert kept.embedding[0] == pytest.approx(0.1)


async def test_reindex_skips_user_without_consent(user):
    async with SessionLocal() as session:
        stored = await session.get(User, user.id)
        stored.ai_transfer_accepted_at = None
        await session.commit()
    lecture_id = await add_lecture(user.id, "текст")

    await reindex_embeddings()

    assert all(chunk.embedding is None for chunk in await load_chunks(lecture_id))


async def test_reindex_continues_after_provider_error(user, monkeypatch):
    broken_id = await add_lecture(user.id, "плохой")
    good_id = await add_lecture(user.id, "хороший")

    class Selective(StubEmbeddings):
        async def embed_documents(self, texts):
            if "плохой" in texts:
                raise OpenAICompatibleError("нет ответа")
            return await super().embed_documents(texts)

    monkeypatch.setattr(reindex, "get_embeddings", Selective)

    await reindex_embeddings()

    assert all(chunk.embedding is None for chunk in await load_chunks(broken_id))
    assert all(chunk.embedding is not None for chunk in await load_chunks(good_id))
