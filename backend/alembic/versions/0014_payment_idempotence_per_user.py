import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TRIM_RAW = """
UPDATE payments SET raw = jsonb_strip_nulls(jsonb_build_object(
    'id', raw->'id',
    'status', raw->'status',
    'amount', raw->'amount',
    'captured_at', raw->'captured_at',
    'confirmation', CASE WHEN raw->'confirmation'->'confirmation_url' IS NOT NULL
        THEN jsonb_build_object('confirmation_url', raw->'confirmation'->'confirmation_url')
    END
))
"""


def upgrade() -> None:
    op.drop_constraint("uq_payments_idempotence_key", "payments", type_="unique")
    op.create_unique_constraint(
        "uq_payments_user_idempotence_key", "payments", ["user_id", "idempotence_key"]
    )
    op.execute(sa.text(TRIM_RAW))


def downgrade() -> None:
    op.drop_constraint("uq_payments_user_idempotence_key", "payments", type_="unique")
    op.create_unique_constraint("uq_payments_idempotence_key", "payments", ["idempotence_key"])
