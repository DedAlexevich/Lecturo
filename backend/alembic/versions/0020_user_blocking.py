import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("blocked_reason", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "blocked_reason")
    op.drop_column("users", "blocked_at")
