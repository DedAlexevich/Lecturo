import os
import re

import asyncpg
import pytest

from app import handlers, notifications, storage

DATABASE_URL = os.environ.get("BOT_SCHEMA_DATABASE_URL")

QUERIES = {
    f"{module.__name__}.{name}": value
    for module in (notifications, storage, handlers)
    for name, value in vars(module).items()
    if name.isupper()
    and isinstance(value, str)
    and re.match(r"\s*(SELECT|UPDATE|INSERT|DELETE|WITH)\b", value)
}


def test_queries_are_collected():
    assert len(QUERIES) >= 14


@pytest.mark.skipif(not DATABASE_URL, reason="BOT_SCHEMA_DATABASE_URL не задан")
@pytest.mark.parametrize("name", sorted(QUERIES))
async def test_query_matches_schema(name):
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        await connection.prepare(QUERIES[name])
    finally:
        await connection.close()
