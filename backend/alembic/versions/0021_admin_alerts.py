import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_alert_signals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('firing', 'resolved', 'event')", name=op.f("ck_admin_alert_signals_state")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_alert_signals")),
    )
    op.create_index(
        "ix_admin_alert_signals_pending",
        "admin_alert_signals",
        ["created_at"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )
    op.create_index(
        "ix_admin_alert_signals_kind_dispatched_at",
        "admin_alert_signals",
        ["kind", "dispatched_at"],
    )
    op.create_table(
        "admin_alert_settings",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "muted_kinds",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("recoveries", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_admin_alert_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_admin_alert_settings")),
    )
    op.create_table(
        "admin_alert_deliveries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_admin_alert_deliveries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_alert_deliveries")),
    )
    op.create_index(
        op.f("ix_admin_alert_deliveries_user_id"), "admin_alert_deliveries", ["user_id"]
    )
    op.create_index(
        "ix_admin_alert_deliveries_pending",
        "admin_alert_deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("sent_at IS NULL AND expired_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("admin_alert_deliveries")
    op.drop_table("admin_alert_settings")
    op.drop_table("admin_alert_signals")
