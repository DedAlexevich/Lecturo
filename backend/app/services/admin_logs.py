import asyncio
import enum
import os
import re
import stat
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings

MAX_LINES = 1000
DEFAULT_LINES = 200
MAX_SCAN_BYTES = 16 * 1024 * 1024
MAX_LINE_CHARS = 4000
STREAM_CHUNK_BYTES = 256 * 1024
STREAM_POLL_SECONDS = 1.0
STREAM_HEARTBEAT_SECONDS = 15.0
STREAM_MAX_SECONDS = 30 * 60
MASK = "***"

LOG_UNAVAILABLE = "Лог не найден или недоступен"
TOO_MANY_STREAMS = "Слишком много открытых потоков логов"


class LogService(enum.StrEnum):
    api = "api"
    worker = "worker"
    bot = "bot"
    caddy = "caddy"
    tusd = "tusd"


class LogLevel(enum.StrEnum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


LEVEL_ORDER = {level: index for index, level in enumerate(LogLevel)}
LEVEL_ALIASES = {
    "warn": LogLevel.warning,
    "fatal": LogLevel.critical,
    "panic": LogLevel.critical,
    "err": LogLevel.error,
}
LEVEL_PATTERNS = (
    re.compile(r"^\S+ \S+ (DEBUG|INFO|WARNING|ERROR|CRITICAL)\b"),
    re.compile(r'"level"\s*:\s*"(\w+)"', re.IGNORECASE),
    re.compile(r"\blevel=(\w+)", re.IGNORECASE),
)

SECRET_NAME = (
    r"(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key"
    r"|authorization|cookie|signature|init[_-]?data|session[_-]?id)"
)
BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}")
KEY_VALUE = re.compile(
    rf"""(?ix)
    (["']?[\w.-]*{SECRET_NAME}[\w.-]*["']?\s*[:=]\s*)
    ("[^"]*"|'[^']*'|\[[^\]]*\]|[^\s,;&}}\]]+)
    """
)
QUERY_SECRET = re.compile(
    r"(?i)([?&][\w%.-]*(?:token|signature|share|code|secret|password|key|sig|auth|state)[\w%.-]*=)"
    r"[^&#\s\"']*"
)
URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+@")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
TELEGRAM_BOT_TOKEN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
PREFIXED_KEY = re.compile(r"\b(?:sk-|pk-|AKIA|AQVN|y0_|age1)[A-Za-z0-9_-]{16,}\b")
LONG_TOKEN = re.compile(
    r"(?<![\w/.-])(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{40,}\b"
)
EMAIL = re.compile(
    r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9-])[A-Za-z0-9.-]*(\.[A-Za-z]{2,})\b"
)


def mask_text(text: str) -> str:
    text = BEARER.sub(rf"\1 {MASK}", text)
    text = KEY_VALUE.sub(rf"\1{MASK}", text)
    text = QUERY_SECRET.sub(rf"\1{MASK}", text)
    text = URL_CREDENTIALS.sub(rf"\1{MASK}@", text)
    text = JWT.sub(MASK, text)
    text = TELEGRAM_BOT_TOKEN.sub(MASK, text)
    text = PREFIXED_KEY.sub(MASK, text)
    text = LONG_TOKEN.sub(MASK, text)
    return EMAIL.sub(rf"\1{MASK}@\2{MASK}\3", text)


def detect_level(line: str) -> LogLevel | None:
    for pattern in LEVEL_PATTERNS:
        found = pattern.search(line)
        if found is None:
            continue
        name = found.group(1).lower()
        if name in LogLevel.__members__:
            return LogLevel(name)
        if name in LEVEL_ALIASES:
            return LEVEL_ALIASES[name]
    return None


def passes(level: LogLevel | None, min_level: LogLevel | None) -> bool:
    if min_level is None:
        return True
    return level is not None and LEVEL_ORDER[level] >= LEVEL_ORDER[min_level]


@dataclass
class LogLine:
    level: LogLevel | None
    text: str


@dataclass
class LogTail:
    lines: list[LogLine]
    offset: int
    size: int
    modified_at: datetime


class LogUnavailable(Exception):
    pass


def log_file_name(service: LogService) -> str:
    return f"{service.value}.log"


def open_log(service: LogService) -> int:
    log_dir = get_settings().log_dir
    if log_dir is None:
        raise LogUnavailable
    try:
        dir_fd = os.open(Path(log_dir), os.O_RDONLY | os.O_DIRECTORY)
    except OSError as error:
        raise LogUnavailable from error
    try:
        fd = os.open(log_file_name(service), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as error:
        raise LogUnavailable from error
    finally:
        os.close(dir_fd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise LogUnavailable
    return fd


def ensure_available(service: LogService) -> None:
    os.close(open_log(service))


def decode_lines(data: bytes) -> list[str]:
    text = data.decode("utf-8", errors="replace")
    return [line[:MAX_LINE_CHARS] for line in text.splitlines()]


def prepare(
    raw_lines: list[str],
    min_level: LogLevel | None,
    query: str,
    inherited: LogLevel | None = None,
) -> tuple[list[LogLine], LogLevel | None]:
    needle = query.lower()
    result: list[LogLine] = []
    current = inherited
    for raw in raw_lines:
        detected = detect_level(raw)
        if detected is not None:
            current = detected
        if not passes(current, min_level):
            continue
        masked = mask_text(raw)
        if needle and needle not in masked.lower():
            continue
        result.append(LogLine(current, masked))
    return result, current


def read_tail_sync(
    service: LogService, count: int, min_level: LogLevel | None, query: str
) -> LogTail:
    fd = open_log(service)
    try:
        info = os.fstat(fd)
        start = max(0, info.st_size - MAX_SCAN_BYTES)
        os.lseek(fd, start, os.SEEK_SET)
        data = os.read(fd, info.st_size - start)
    finally:
        os.close(fd)
    raw_lines = decode_lines(data)
    if start > 0 and raw_lines:
        raw_lines = raw_lines[1:]
    lines, _ = prepare(raw_lines, min_level, query)
    return LogTail(
        lines=lines[-count:],
        offset=info.st_size,
        size=info.st_size,
        modified_at=datetime.fromtimestamp(info.st_mtime, UTC),
    )


async def read_tail(
    service: LogService, count: int, min_level: LogLevel | None, query: str
) -> LogTail:
    return await asyncio.to_thread(read_tail_sync, service, count, min_level, query)


def read_new_sync(service: LogService, offset: int) -> tuple[bytes, int, bool]:
    fd = open_log(service)
    try:
        size = os.fstat(fd).st_size
        restarted = size < offset
        position = 0 if restarted else offset
        if size == position:
            return b"", position, restarted
        os.lseek(fd, position, os.SEEK_SET)
        data = os.read(fd, min(STREAM_CHUNK_BYTES, size - position))
    finally:
        os.close(fd)
    end = data.rfind(b"\n")
    if end == -1:
        if len(data) < STREAM_CHUNK_BYTES:
            return b"", position, restarted
        end = len(data) - 1
    return data[: end + 1], position + end + 1, restarted


class StreamSlots:
    def __init__(self) -> None:
        self.active = 0

    def acquire(self, limit: int) -> bool:
        if self.active >= limit:
            return False
        self.active += 1
        return True

    def release(self) -> None:
        self.active = max(0, self.active - 1)


stream_slots = StreamSlots()


@dataclass
class StreamChunk:
    lines: list[LogLine]
    offset: int
    restarted: bool


async def follow(
    service: LogService,
    min_level: LogLevel | None,
    query: str,
    offset: int | None,
    sleep=asyncio.sleep,
) -> AsyncIterator[StreamChunk | None]:
    if offset is None:
        fd = open_log(service)
        try:
            offset = os.fstat(fd).st_size
        finally:
            os.close(fd)
    inherited: LogLevel | None = None
    while True:
        try:
            data, offset, restarted = await asyncio.to_thread(read_new_sync, service, offset)
        except LogUnavailable:
            data, restarted = b"", False
        if data:
            lines, inherited = prepare(decode_lines(data), min_level, query, inherited)
            yield StreamChunk(lines, offset, restarted)
        else:
            yield None
        await sleep(STREAM_POLL_SECONDS)
