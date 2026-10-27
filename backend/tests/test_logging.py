import logging
import re
from logging.handlers import RotatingFileHandler

import pytest

from app.core.config import get_settings
from app.core.logging import configure_logging


@pytest.fixture
def isolated_loggers():
    names = ["", "app", "uvicorn", "uvicorn.access"]
    loggers = [logging.getLogger(name) for name in names]
    saved = [(logger.handlers[:], logger.level, logger.propagate) for logger in loggers]
    for logger in loggers:
        logger.handlers.clear()
    yield
    for logger, (handlers, level, propagate) in zip(loggers, saved, strict=True):
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate
    get_settings.cache_clear()


def test_logs_are_written_to_rotating_file(tmp_path, monkeypatch, isolated_loggers):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_SERVICE", "worker")
    monkeypatch.setenv("LOG_MAX_MB", "2")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "3")
    get_settings.cache_clear()
    logging.getLogger("uvicorn").propagate = False
    configure_logging()
    configure_logging()
    logging.getLogger("app.pipeline.media").info("ffmpeg упал")
    logging.getLogger("uvicorn.error").error("сервер упал")
    logging.getLogger("yt_dlp").warning("сторонняя ошибка")
    handlers = [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 2 * 1024 * 1024
    assert handlers[0].backupCount == 3
    handlers[0].flush()
    lines = (tmp_path / "worker.log").read_text().splitlines()
    assert len(lines) == 3
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} INFO worker app\.pipeline\.media: ffmpeg упал",
        lines[0],
    )
    assert "ERROR worker uvicorn.error: сервер упал" in lines[1]
    assert "WARNING worker yt_dlp: сторонняя ошибка" in lines[2]


def test_no_file_without_log_dir(monkeypatch, isolated_loggers):
    monkeypatch.delenv("LOG_DIR", raising=False)
    get_settings.cache_clear()
    configure_logging()
    assert not [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]
