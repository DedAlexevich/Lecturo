import asyncio
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from app.core.db import SessionLocal, engine

BACKEND = Path(__file__).resolve().parents[1]
FK_INDEXES = {
    "ix_usage_entries_lecture_id",
    "ix_usage_entries_package_id",
    "ix_share_links_lecture_id",
    "ix_share_links_course_id",
    "ix_share_links_owner_id",
    "ix_course_lectures_lecture_id",
    "ix_auth_tokens_user_id",
    "ix_complaints_lecture_id",
    "ix_subscriptions_payment_id",
    "ix_hour_packages_payment_id",
}


async def alembic(*args: str) -> None:
    await asyncio.to_thread(
        subprocess.run, [sys.executable, "-m", "alembic", *args], cwd=BACKEND, check=True
    )
    await engine.dispose()


async def schema_state() -> tuple[set[str], bool]:
    async with SessionLocal() as session:
        indexes = set(
            await session.scalars(
                text("SELECT indexname FROM pg_indexes WHERE indexname = ANY(:names)"),
                {"names": list(FK_INDEXES)},
            )
        )
        unique = await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_constraint "
                "WHERE conname = 'uq_auth_identities_user_id')"
            )
        )
    return indexes, unique


async def test_fk_indexes_migration_removes_duplicates_and_rolls_back():
    user_id = uuid.uuid4()
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    created = datetime.now(UTC) - timedelta(days=1)
    await alembic("downgrade", "0012")
    try:
        assert await schema_state() == (set(), False)
        async with SessionLocal() as session:
            await session.execute(
                text("INSERT INTO users (id, display_name) VALUES (:id, 'Дубли')"), {"id": user_id}
            )
            await session.execute(
                text(
                    "INSERT INTO auth_identities "
                    "(id, user_id, provider, provider_user_id, data, created_at) VALUES "
                    "(:first, :user, 'vk', :first_vk, '{}', :older), "
                    "(:second, :user, 'vk', :second_vk, '{}', :newer)"
                ),
                {
                    "first": first_id,
                    "second": second_id,
                    "user": user_id,
                    "first_vk": f"vk-{first_id}",
                    "second_vk": f"vk-{second_id}",
                    "older": created,
                    "newer": created + timedelta(minutes=1),
                },
            )
            await session.commit()

        await alembic("upgrade", "head")

        assert await schema_state() == (FK_INDEXES, True)
        async with SessionLocal() as session:
            kept = await session.scalars(
                text("SELECT id FROM auth_identities WHERE user_id = :user"), {"user": user_id}
            )
            assert list(kept) == [first_id]

        await alembic("downgrade", "0012")
        assert await schema_state() == (set(), False)
    finally:
        await alembic("upgrade", "head")
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            await session.commit()
