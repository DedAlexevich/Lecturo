import asyncio
import logging

import pytest

from app.main import serve


async def failing():
    raise ConnectionResetError()


async def test_failed_background_task_stops_bot(caplog):
    polling = asyncio.ensure_future(asyncio.Event().wait())
    task = asyncio.create_task(failing(), name="quotas")
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as stopped:
        await serve(polling, [task])
    assert stopped.value.code == 1
    assert polling.cancelled()
    assert "Фоновая задача quotas остановилась" in caplog.text
    assert "ConnectionResetError" in caplog.text


async def test_bot_stops_quietly_when_polling_ends():
    task = asyncio.create_task(asyncio.Event().wait())
    await serve(asyncio.sleep(0), [task])
    assert not task.done()
    task.cancel()
