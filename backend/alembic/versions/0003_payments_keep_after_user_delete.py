import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("payments", "user_id", existing_type=sa.UUID(), nullable=True)
    op.drop_constraint("fk_payments_user_id_users", "payments", type_="foreignkey")
    op.create_foreign_key(
        "fk_payments_user_id_users",
        "payments",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.execute("DELETE FROM payments WHERE user_id IS NULL")
    op.drop_constraint("fk_payments_user_id_users", "payments", type_="foreignkey")
    op.create_foreign_key(
        "fk_payments_user_id_users",
        "payments",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("payments", "user_id", existing_type=sa.UUID(), nullable=False)
