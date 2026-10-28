import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("search_chunks", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("search_chunks", "description")
