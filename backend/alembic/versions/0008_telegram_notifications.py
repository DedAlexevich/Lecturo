import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_identities", sa.Column("bot_started_at", sa.DateTime(timezone=True)))
    op.add_column("auth_identities", sa.Column("bot_blocked_at", sa.DateTime(timezone=True)))
    op.create_table(
        "notification_events",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("lecture_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("lecture", "regenerate", "quiz", name="notification_kind"),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum("ready", "failed", name="notification_outcome"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lecture_id"],
            ["lectures.id"],
            name=op.f("fk_notification_events_lecture_id_lectures"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notification_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_events")),
    )
    op.create_index(
        op.f("ix_notification_events_lecture_id"),
        "notification_events",
        ["lecture_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_events_user_id"), "notification_events", ["user_id"], unique=False
    )
    op.create_index(
        "ix_notification_events_pending",
        "notification_events",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("sent_at IS NULL AND expired_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notification_events_pending", table_name="notification_events")
    op.drop_index(op.f("ix_notification_events_user_id"), table_name="notification_events")
    op.drop_index(op.f("ix_notification_events_lecture_id"), table_name="notification_events")
    op.drop_table("notification_events")
    op.execute("DROP TYPE IF EXISTS notification_kind")
    op.execute("DROP TYPE IF EXISTS notification_outcome")
    op.drop_column("auth_identities", "bot_blocked_at")
    op.drop_column("auth_identities", "bot_started_at")
