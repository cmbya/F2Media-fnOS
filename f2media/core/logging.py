from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock

from .redact import redact_text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("f2media")
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.handlers.clear()
    fmt = RedactingFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    file_handler = RotatingFileHandler(
        log_dir / "f2media.log", maxBytes=8 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)
    logger.propagate = False
    return logger


class TaskLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def write(self, level: str, message: str) -> None:
        from datetime import datetime

        line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} | {level.upper():7} | {redact_text(message)}\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)

    def tail(self, max_bytes: int = 256_000) -> str:
        if not self.path.exists():
            return ""
        with self.path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
