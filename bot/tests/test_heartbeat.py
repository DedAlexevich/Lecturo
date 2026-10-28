import asyncio
import os
import time

from app.heartbeat import heartbeat_loop, is_alive


def test_missing_file_is_not_alive(tmp_path):
    assert not is_alive(tmp_path / "heartbeat")


def test_stale_file_is_not_alive(tmp_path):
    path = tmp_path / "heartbeat"
    path.touch()
    old = time.time() - 120
    os.utime(path, (old, old))
    assert not is_alive(path, max_age=90)


async def test_loop_touches_file(tmp_path):
    path = tmp_path / "heartbeat"
    task = asyncio.create_task(heartbeat_loop(path, interval=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    assert is_alive(path)
