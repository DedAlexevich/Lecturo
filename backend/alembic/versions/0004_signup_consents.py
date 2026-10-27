import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("terms_revision", sa.Date()))
    op.add_column("users", sa.Column("personal_data_accepted_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("personal_data_revision", sa.Date()))


def downgrade() -> None:
    op.drop_column("users", "personal_data_revision")
    op.drop_column("users", "personal_data_accepted_at")
    op.drop_column("users", "terms_revision")
    op.drop_column("users", "terms_accepted_at")
