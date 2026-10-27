import asyncio
import logging
import uuid

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Lecture, SearchChunk
from app.pipeline.stages import ConsentMissing, require_ai_transfer
from app.providers import get_embeddings
from app.providers.openai_compat import OpenAICompatibleError

logger = logging.getLogger(__name__)

BATCH_SIZE = 32


async def reindex_embeddings() -> int:
    embeddings = get_embeddings()
    async with SessionLocal() as session:
        lecture_ids = list(
            await session.scalars(
                select(SearchChunk.lecture_id)
                .where(SearchChunk.embedding.is_(None))
                .distinct()
                .order_by(SearchChunk.lecture_id)
            )
        )
    total = 0
    for lecture_id in lecture_ids:
        try:
            total += await reindex_lecture(embeddings, lecture_id)
        except ConsentMissing:
            logger.warning("Лекция %s пропущена: нет согласия на передачу данных", lecture_id)
        except OpenAICompatibleError:
            logger.exception("Лекция %s пропущена: не удалось получить эмбеддинги", lecture_id)
    return total


async def reindex_lecture(embeddings, lecture_id: uuid.UUID) -> int:
    async with SessionLocal() as session:
        lecture = await session.get(Lecture, lecture_id)
        if lecture is None:
            return 0
        await require_ai_transfer(session, lecture)
        chunks = list(
            await session.scalars(
                select(SearchChunk)
                .where(SearchChunk.lecture_id == lecture_id, SearchChunk.embedding.is_(None))
                .order_by(SearchChunk.id)
            )
        )
        for offset in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[offset : offset + BATCH_SIZE]
            vectors = await embeddings.embed_documents([chunk.text for chunk in batch])
            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector
        await session.commit()
        return len(chunks)


if __name__ == "__main__":
    print(f"Пересчитано фрагментов: {asyncio.run(reindex_embeddings())}")
