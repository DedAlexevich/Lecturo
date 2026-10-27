import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import Settings, get_settings

APP_LOGGER_NAME = "app"
OWN_OUTPUT_LOGGERS = ("app", "arq", "uvicorn")
SERVER_LOGGERS = ("uvicorn", "uvicorn.access")


class WithoutOwnOutput(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.split(".")[0] not in OWN_OUTPUT_LOGGERS


def build_formatter(service: str) -> logging.Formatter:
    return logging.Formatter(f"%(asctime)s %(levelname)s {service} %(name)s: %(message)s")


def attach_file_logging(settings: Settings, log_dir: Path, formatter: logging.Formatter) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / f"{settings.log_service}.log",
        maxBytes=settings.log_max_mb * 1024 * 1024,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)
    stderr_handler.addFilter(WithoutOwnOutput())
    root = logging.getLogger()
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)
    for name in SERVER_LOGGERS:
        server_logger = logging.getLogger(name)
        if not server_logger.propagate:
            server_logger.addHandler(file_handler)


def configure_logging() -> None:
    settings = get_settings()
    formatter = build_formatter(settings.log_service)
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    if settings.log_dir is not None:
        attach_file_logging(settings, settings.log_dir, formatter)
