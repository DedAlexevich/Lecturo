import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

notice_channel = sa.Enum("email", "telegram", name="notice_channel")


def upgrade() -> None:
    op.create_table(
        "legal_revisions",
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("revision_date", sa.Date(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column(
            "announced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("slug", "revision_date", name=op.f("pk_legal_revisions")),
    )
    op.create_table(
        "legal_notices",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("revision_date", sa.Date(), nullable=False),
        sa.Column("channel", notice_channel, nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("link", sa.String(length=512), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_legal_notices_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legal_notices")),
        sa.UniqueConstraint(
            "user_id",
            "slug",
            "revision_date",
            "channel",
            name=op.f("uq_legal_notices_user_id"),
        ),
    )


def downgrade() -> None:
    op.drop_table("legal_notices")
    op.drop_table("legal_revisions")
    notice_channel.drop(op.get_bind())
