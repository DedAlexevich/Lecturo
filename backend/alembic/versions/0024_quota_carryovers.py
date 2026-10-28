import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quota_carryovers",
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("used_sec", sa.Integer(), nullable=False),
        sa.Column("week_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("identity_hash", name=op.f("pk_quota_carryovers")),
    )
    op.create_index(
        op.f("ix_quota_carryovers_week_ends_at"), "quota_carryovers", ["week_ends_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_quota_carryovers_week_ends_at"), table_name="quota_carryovers")
    op.drop_table("quota_carryovers")
