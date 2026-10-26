import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "quota_week_start",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "auth_identities",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum("email", "telegram", "vk", "yandex", name="auth_provider"),
            nullable=False,
        ),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name=op.f("fk_auth_identities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_identities")),
        sa.UniqueConstraint(
            "provider", "provider_user_id", name=op.f("uq_auth_identities_provider")
        ),
    )
    op.create_table(
        "auth_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("verify_email", "reset_password", name="auth_token_kind"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_tokens_token_hash")),
    )
    op.create_table(
        "courses",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_courses_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_courses")),
    )
    op.create_index(op.f("ix_courses_owner_id"), "courses", ["owner_id"], unique=False)
    op.create_table(
        "lectures",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column(
            "source_type", sa.Enum("upload", "link", "local", name="source_type"), nullable=False
        ),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("embed_url", sa.Text(), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "waiting_quota", "processing", "ready", "failed", name="lecture_status"
            ),
            nullable=False,
        ),
        sa.Column("queue_position", sa.Integer(), nullable=True),
        sa.Column("video_path", sa.Text(), nullable=True),
        sa.Column("audio_path", sa.Text(), nullable=True),
        sa.Column("video_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_locally", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_lectures_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lectures")),
    )
    op.create_index(op.f("ix_lectures_owner_id"), "lectures", ["owner_id"], unique=False)
    op.create_table(
        "payments",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Enum("subscription", "package", name="payment_kind"), nullable=False),
        sa.Column("product_code", sa.String(length=64), nullable=False),
        sa.Column("amount_kopecks", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "succeeded", "canceled", name="payment_status"),
            nullable=False,
        ),
        sa.Column("idempotence_key", sa.String(length=64), nullable=False),
        sa.Column("yookassa_id", sa.String(length=64), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_payments_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("idempotence_key", name=op.f("uq_payments_idempotence_key")),
        sa.UniqueConstraint("yookassa_id", name=op.f("uq_payments_yookassa_id")),
    )
    op.create_index(op.f("ix_payments_user_id"), "payments", ["user_id"], unique=False)
    op.create_table(
        "chapters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_id", sa.UUID(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("start", sa.Float(), nullable=False),
        sa.Column("end", sa.Float(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["lecture_id"],
            ["lectures.id"],
            name=op.f("fk_chapters_lecture_id_lectures"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chapters")),
    )
    op.create_index(op.f("ix_chapters_lecture_id"), "chapters", ["lecture_id"], unique=False)
    op.create_table(
        "complaints",
        sa.Column("lecture_id", sa.UUID(), nullable=False),
        sa.Column("reporter_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_complaints_lecture_id_lectures"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"],
            ["users.id"],
            name=op.f("fk_complaints_reporter_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_complaints")),
    )
    op.create_table(
        "course_lectures",
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("lecture_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_course_lectures_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lecture_id"],
            ["lectures.id"],
            name=op.f("fk_course_lectures_lecture_id_lectures"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("course_id", "lecture_id", name=op.f("pk_course_lectures")),
    )
    op.create_table(
        "exam_sheets",
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_exam_sheets_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_sheets")),
        sa.UniqueConstraint("course_id", name=op.f("uq_exam_sheets_course_id")),
    )
    op.create_table(
        "hour_packages",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column("seconds_total", sa.Integer(), nullable=False),
        sa.Column("seconds_left", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name=op.f("fk_hour_packages_payment_id_payments")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_hour_packages_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hour_packages")),
    )
    op.create_index(op.f("ix_hour_packages_user_id"), "hour_packages", ["user_id"], unique=False)
    op.create_table(
        "processing_steps",
        sa.Column("lecture_id", sa.UUID(), nullable=False),
        sa.Column(
            "step",
            sa.Enum(
                "download",
                "audio",
                "video",
                "transcribe",
                "summarize",
                "embed",
                "quiz",
                name="step_name",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "failed", name="step_status"),
            nullable=False,
        ),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_processing_steps_lecture_id_lectures"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_steps")),
        sa.UniqueConstraint("lecture_id", "step", name=op.f("uq_processing_steps_lecture_id")),
    )
    op.create_table(
        "quizzes",
        sa.Column("lecture_id", sa.UUID(), nullable=False),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name=op.f("fk_quizzes_lecture_id_lectures"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quizzes")),
        sa.UniqueConstraint("lecture_id", name=op.f("uq_quizzes_lecture_id")),
    )
    op.create_table(
        "search_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_id", sa.UUID(), nullable=False),
        sa.Column("start", sa.Float(), nullable=False),
        sa.Column("end", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('russian', text)", persisted=True),
            nullable=False,
        ),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.ForeignKeyConstraint(
            ["lecture_id"],
            ["lectures.id"],
            name=op.f("fk_search_chunks_lecture_id_lectures"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_chunks")),
    )
    op.create_index(
        "ix_search_chunks_embedding",
        "search_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        op.f("ix_search_chunks_lecture_id"), "search_chunks", ["lecture_id"], unique=False
    )
    op.create_index(
        "ix_search_chunks_tsv", "search_chunks", ["tsv"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "share_links",
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("lecture_id", sa.UUID(), nullable=True),
        sa.Column("course_id", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(lecture_id IS NULL) <> (course_id IS NULL)", name=op.f("ck_share_links_one_target")
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name=op.f("fk_share_links_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lecture_id"],
            ["lectures.id"],
            name=op.f("fk_share_links_lecture_id_lectures"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_share_links_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_links")),
        sa.UniqueConstraint("token", name=op.f("uq_share_links_token")),
    )
    op.create_table(
        "subscriptions",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name=op.f("fk_subscriptions_payment_id_payments")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_subscriptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index(op.f("ix_subscriptions_user_id"), "subscriptions", ["user_id"], unique=False)
    op.create_table(
        "summaries",
        sa.Column("lecture_id", sa.UUID(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lecture_id"],
            ["lectures.id"],
            name=op.f("fk_summaries_lecture_id_lectures"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("lecture_id", name=op.f("pk_summaries")),
    )
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lecture_id", sa.UUID(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("start", sa.Float(), nullable=False),
        sa.Column("end", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["lecture_id"],
            ["lectures.id"],
            name=op.f("fk_transcript_segments_lecture_id_lectures"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transcript_segments")),
    )
    op.create_index(
        op.f("ix_transcript_segments_lecture_id"),
        "transcript_segments",
        ["lecture_id"],
        unique=False,
    )
    op.create_table(
        "usage_entries",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("lecture_id", sa.UUID(), nullable=True),
        sa.Column(
            "source",
            sa.Enum("weekly", "package", "local_embeddings", name="usage_source"),
            nullable=False,
        ),
        sa.Column("package_id", sa.UUID(), nullable=True),
        sa.Column("seconds", sa.Integer(), nullable=False),
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
            name=op.f("fk_usage_entries_lecture_id_lectures"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["hour_packages.id"],
            name=op.f("fk_usage_entries_package_id_hour_packages"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_usage_entries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_entries")),
    )
    op.create_index(op.f("ix_usage_entries_user_id"), "usage_entries", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_usage_entries_user_id"), table_name="usage_entries")
    op.drop_table("usage_entries")
    op.drop_index(op.f("ix_transcript_segments_lecture_id"), table_name="transcript_segments")
    op.drop_table("transcript_segments")
    op.drop_table("summaries")
    op.drop_index(op.f("ix_subscriptions_user_id"), table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("share_links")
    op.drop_index("ix_search_chunks_tsv", table_name="search_chunks", postgresql_using="gin")
    op.drop_index(op.f("ix_search_chunks_lecture_id"), table_name="search_chunks")
    op.drop_index(
        "ix_search_chunks_embedding",
        table_name="search_chunks",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("search_chunks")
    op.drop_table("quizzes")
    op.drop_table("processing_steps")
    op.drop_index(op.f("ix_hour_packages_user_id"), table_name="hour_packages")
    op.drop_table("hour_packages")
    op.drop_table("exam_sheets")
    op.drop_table("course_lectures")
    op.drop_table("complaints")
    op.drop_index(op.f("ix_chapters_lecture_id"), table_name="chapters")
    op.drop_table("chapters")
    op.drop_index(op.f("ix_payments_user_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_index(op.f("ix_lectures_owner_id"), table_name="lectures")
    op.drop_table("lectures")
    op.drop_index(op.f("ix_courses_owner_id"), table_name="courses")
    op.drop_table("courses")
    op.drop_table("auth_tokens")
    op.drop_table("auth_identities")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS auth_provider")
    op.execute("DROP TYPE IF EXISTS auth_token_kind")
    op.execute("DROP TYPE IF EXISTS source_type")
    op.execute("DROP TYPE IF EXISTS lecture_status")
    op.execute("DROP TYPE IF EXISTS step_name")
    op.execute("DROP TYPE IF EXISTS step_status")
    op.execute("DROP TYPE IF EXISTS payment_kind")
    op.execute("DROP TYPE IF EXISTS payment_status")
    op.execute("DROP TYPE IF EXISTS usage_source")
