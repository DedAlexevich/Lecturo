import os
import re

import asyncpg
import pytest

from app import alerts, handlers, notifications, storage

SCHEMA_CHECK = os.environ.get("BOT_SCHEMA_CHECK") == "1"

QUERIES = {
    f"{module.__name__}.{name}": value
    for module in (notifications, storage, handlers, alerts)
    for name, value in vars(module).items()
    if name.isupper()
    and isinstance(value, str)
    and re.match(r"\s*(SELECT|UPDATE|INSERT|DELETE|WITH)\b", value)
}


def test_queries_are_collected():
    assert len(QUERIES) >= 30


@pytest.mark.skipif(not SCHEMA_CHECK, reason="BOT_SCHEMA_CHECK не задан")
@pytest.mark.parametrize("name", sorted(QUERIES))
async def test_query_matches_schema(name):
    connection = await asyncpg.connect()
    try:
        await connection.prepare(QUERIES[name])
    finally:
        await connection.close()
