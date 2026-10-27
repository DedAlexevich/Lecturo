import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging() -> None:
    service = os.environ.get("LOG_SERVICE", "bot")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_dir = os.environ.get("LOG_DIR", "").strip()
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                Path(log_dir) / f"{service}.log",
                maxBytes=int(os.environ.get("LOG_MAX_MB", 10)) * 1024 * 1024,
                backupCount=int(os.environ.get("LOG_BACKUP_COUNT", 5)),
                encoding="utf-8",
            )
        )
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s %(levelname)s {service} %(name)s: %(message)s",
        handlers=handlers,
    )
