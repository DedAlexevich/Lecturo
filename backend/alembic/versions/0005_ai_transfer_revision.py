import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("ai_transfer_revision", sa.Date()))
    op.execute(
        "UPDATE users SET ai_transfer_revision = DATE '2026-10-26' "
        "WHERE ai_transfer_accepted_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "ai_transfer_revision")
