import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("user_label", sa.String(length=320), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_business_events")),
    )
    op.create_index(op.f("ix_business_events_user_id"), "business_events", ["user_id"])
    op.create_index("ix_business_events_created_at", "business_events", ["created_at"])
    op.create_index("ix_business_events_kind_created_at", "business_events", ["kind", "created_at"])


def downgrade() -> None:
    op.drop_table("business_events")
