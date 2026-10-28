import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("hours", sa.Integer(), nullable=True),
        sa.Column("days", sa.Integer(), nullable=True),
        sa.Column("discount_percent", sa.Integer(), nullable=True),
        sa.Column("discount_kopecks", sa.Integer(), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_promo_codes_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promo_codes")),
        sa.UniqueConstraint("code", name=op.f("uq_promo_codes_code")),
    )
    op.create_index(op.f("ix_promo_codes_created_by"), "promo_codes", ["created_by"], unique=False)
    op.create_table(
        "promo_redemptions",
        sa.Column("promo_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name=op.f("fk_promo_redemptions_payment_id_payments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["promo_id"],
            ["promo_codes.id"],
            name=op.f("fk_promo_redemptions_promo_id_promo_codes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_promo_redemptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promo_redemptions")),
    )
    op.create_index(
        op.f("ix_promo_redemptions_payment_id"), "promo_redemptions", ["payment_id"], unique=False
    )
    op.create_index(
        "ix_promo_redemptions_promo_id_user_id",
        "promo_redemptions",
        ["promo_id", "user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_promo_redemptions_user_id"), "promo_redemptions", ["user_id"], unique=False
    )
    op.add_column(
        "payments", sa.Column("discount_kopecks", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("payments", "discount_kopecks")
    op.drop_table("promo_redemptions")
    op.drop_table("promo_codes")
