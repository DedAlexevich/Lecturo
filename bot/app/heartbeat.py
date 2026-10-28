import asyncio
import sys
import time
from pathlib import Path

HEARTBEAT_PATH = Path("/tmp/bot-heartbeat")
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_MAX_AGE_SECONDS = 90


async def heartbeat_loop(
    path: Path = HEARTBEAT_PATH, interval: float = HEARTBEAT_INTERVAL_SECONDS
) -> None:
    while True:
        await asyncio.to_thread(path.touch)
        await asyncio.sleep(interval)


def is_alive(path: Path = HEARTBEAT_PATH, max_age: float = HEARTBEAT_MAX_AGE_SECONDS) -> bool:
    try:
        return time.time() - path.stat().st_mtime < max_age
    except FileNotFoundError:
        return False


if __name__ == "__main__":
    sys.exit(0 if is_alive() else 1)
