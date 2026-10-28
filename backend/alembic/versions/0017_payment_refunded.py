from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE payment_status ADD VALUE IF NOT EXISTS 'refunded'")
    op.execute(
        "UPDATE payments SET status = 'refunded' "
        "WHERE status = 'succeeded' AND raw ? 'refunded_amount'"
    )


def downgrade() -> None:
    op.execute("UPDATE payments SET status = 'succeeded' WHERE status = 'refunded'")
    op.execute("ALTER TYPE payment_status RENAME TO payment_status_old")
    op.execute("CREATE TYPE payment_status AS ENUM ('pending', 'succeeded', 'canceled')")
    op.execute(
        "ALTER TABLE payments ALTER COLUMN status TYPE payment_status "
        "USING status::text::payment_status"
    )
    op.execute("DROP TYPE payment_status_old")
