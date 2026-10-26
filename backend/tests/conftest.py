from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.main import app
from app.models import Payment, User


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def user() -> AsyncIterator[User]:
    async with SessionLocal() as session:
        user = User(display_name="Тест")
        session.add(user)
        await session.commit()
        yield user
        payment_ids = (
            await session.scalars(select(Payment.id).where(Payment.user_id == user.id))
        ).all()
        await session.delete(user)
        await session.execute(delete(Payment).where(Payment.id.in_(payment_ids)))
        await session.commit()


@pytest.fixture
def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}
