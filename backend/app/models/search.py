import enum
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, Enum, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import EMBEDDING_DIM, Base


class ChunkKind(enum.StrEnum):
    transcript = "transcript"
    chapter = "chapter"
    summary = "summary"


class SearchChunk(Base):
    __tablename__ = "search_chunks"
    __table_args__ = (
        Index("ix_search_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_search_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lecture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lectures.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ChunkKind] = mapped_column(
        Enum(ChunkKind, name="chunk_kind"),
        default=ChunkKind.transcript,
        server_default=ChunkKind.transcript.value,
    )
    start: Mapped[float | None] = mapped_column(Float)
    end: Mapped[float | None] = mapped_column(Float)
    section: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('russian', text)", persisted=True)
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
