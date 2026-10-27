import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("auth_tokens", sa.Column("email", sa.String(length=320), nullable=True))


def downgrade() -> None:
    op.drop_column("auth_tokens", "email")
    op.drop_column("users", "token_version")
