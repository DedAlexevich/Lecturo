import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

chunk_kind = sa.Enum("transcript", "chapter", "summary", name="chunk_kind")


def upgrade() -> None:
    chunk_kind.create(op.get_bind())
    op.add_column(
        "search_chunks",
        sa.Column("kind", chunk_kind, server_default="transcript", nullable=False),
    )
    op.add_column("search_chunks", sa.Column("section", sa.Integer(), nullable=True))
    op.alter_column("search_chunks", "start", existing_type=sa.Float(), nullable=True)
    op.alter_column("search_chunks", "end", existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM search_chunks WHERE kind <> 'transcript'")
    op.alter_column("search_chunks", "end", existing_type=sa.Float(), nullable=False)
    op.alter_column("search_chunks", "start", existing_type=sa.Float(), nullable=False)
    op.drop_column("search_chunks", "section")
    op.drop_column("search_chunks", "kind")
    chunk_kind.drop(op.get_bind())
