from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def change_dimension(dimension: int) -> None:
    op.execute("DROP INDEX IF EXISTS ix_search_chunks_embedding")
    op.execute("UPDATE search_chunks SET embedding = NULL")
    op.execute(f"ALTER TABLE search_chunks ALTER COLUMN embedding TYPE vector({dimension})")
    op.execute(
        "CREATE INDEX ix_search_chunks_embedding ON search_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def upgrade() -> None:
    change_dimension(256)


def downgrade() -> None:
    change_dimension(1024)
