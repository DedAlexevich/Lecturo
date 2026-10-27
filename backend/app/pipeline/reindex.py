import asyncio

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import SearchChunk
from app.providers import get_embeddings

BATCH_SIZE = 32


async def reindex_embeddings() -> int:
    embeddings = get_embeddings()
    total = 0
    async with SessionLocal() as session:
        while True:
            chunks = list(
                await session.scalars(
                    select(SearchChunk)
                    .where(SearchChunk.embedding.is_(None))
                    .order_by(SearchChunk.id)
                    .limit(BATCH_SIZE)
                )
            )
            if not chunks:
                return total
            vectors = await embeddings.embed_documents([chunk.text for chunk in chunks])
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = vector
            await session.commit()
            total += len(chunks)


if __name__ == "__main__":
    print(f"Пересчитано фрагментов: {asyncio.run(reindex_embeddings())}")
