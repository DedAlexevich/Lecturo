import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processing_steps", sa.Column("stage", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("processing_steps", "stage")
