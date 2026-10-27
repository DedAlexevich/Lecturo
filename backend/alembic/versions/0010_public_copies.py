import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lectures", sa.Column("copied_from_id", sa.UUID(), nullable=True))
    op.add_column("courses", sa.Column("copied_from_id", sa.UUID(), nullable=True))
    op.create_index(
        "uq_lectures_owner_copied_from",
        "lectures",
        ["owner_id", "copied_from_id"],
        unique=True,
        postgresql_where=sa.text("copied_from_id IS NOT NULL"),
    )
    op.create_index(
        "uq_courses_owner_copied_from",
        "courses",
        ["owner_id", "copied_from_id"],
        unique=True,
        postgresql_where=sa.text("copied_from_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_courses_owner_copied_from", table_name="courses")
    op.drop_index("uq_lectures_owner_copied_from", table_name="lectures")
    op.drop_column("courses", "copied_from_id")
    op.drop_column("lectures", "copied_from_id")
