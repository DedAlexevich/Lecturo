from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

INDEXES = [
    ("usage_entries", "lecture_id"),
    ("usage_entries", "package_id"),
    ("share_links", "lecture_id"),
    ("share_links", "course_id"),
    ("share_links", "owner_id"),
    ("course_lectures", "lecture_id"),
    ("auth_tokens", "user_id"),
    ("complaints", "lecture_id"),
    ("subscriptions", "payment_id"),
    ("hour_packages", "payment_id"),
]


def upgrade() -> None:
    op.execute("LOCK TABLE auth_identities IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        """
        DELETE FROM auth_identities AS duplicate
        USING auth_identities AS kept
        WHERE duplicate.user_id = kept.user_id
          AND duplicate.provider = kept.provider
          AND (duplicate.created_at, duplicate.id) > (kept.created_at, kept.id)
        """
    )
    op.create_unique_constraint(
        op.f("uq_auth_identities_user_id"), "auth_identities", ["user_id", "provider"]
    )
    with op.get_context().autocommit_block():
        for table, column in INDEXES:
            op.create_index(
                op.f(f"ix_{table}_{column}"),
                table,
                [column],
                postgresql_concurrently=True,
                if_not_exists=True,
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for table, column in reversed(INDEXES):
            op.drop_index(
                op.f(f"ix_{table}_{column}"),
                table_name=table,
                postgresql_concurrently=True,
                if_exists=True,
            )
    op.drop_constraint(op.f("uq_auth_identities_user_id"), "auth_identities", type_="unique")
