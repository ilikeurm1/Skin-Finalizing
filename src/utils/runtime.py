from __future__ import annotations

import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from .constants import (
    BACKUP_DIRECTORY_NAME,
    DEFAULT_LOG_LEVEL,
    LOG_DIRECTORY_NAME,
    LOGGER_NAME,
    LOG_LEVEL_WIDTH,
)

LOGGER: logging.Logger = logging.getLogger(LOGGER_NAME)


class CenteredLevelFormatter(logging.Formatter):
    def __init__(
        self, *args: Any, level_width: int = LOG_LEVEL_WIDTH, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.level_width: int = level_width

    def format(self, record: logging.LogRecord) -> str:
        original_levelname: str = record.levelname
        record.levelname = original_levelname.center(self.level_width)
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


def parse_log_level(value: str) -> int:
    normalized: str = value.strip().upper()
    resolved: Any | None = getattr(logging, normalized, None)
    if not isinstance(resolved, int):
        raise ValueError(f"Unsupported log level: {value}")
    return resolved


def build_log_path(base_dir: Path) -> Path:
    logs_dir: Path = base_dir / LOG_DIRECTORY_NAME
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
    return logs_dir / f"skin_finalizing.{timestamp}.log"


def configure_logging(base_dir: Path, log_level_name: str = DEFAULT_LOG_LEVEL) -> Path:
    log_level: int = parse_log_level(log_level_name)
    log_path: Path = build_log_path(base_dir)

    LOGGER.setLevel(logging.DEBUG)
    LOGGER.propagate = False

    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
        handler.close()

    console_handler: logging.StreamHandler[TextIO | Any] = logging.StreamHandler(
        sys.stdout
    )
    console_handler.setLevel(log_level)
    console_handler.setFormatter(
        CenteredLevelFormatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        CenteredLevelFormatter(
            "%(asctime)s | %(levelname)s | %(funcName)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    LOGGER.addHandler(console_handler)
    LOGGER.addHandler(file_handler)
    LOGGER.debug(
        "Logging configured with console level %s and file %s",
        logging.getLevelName(log_level),
        log_path,
    )
    return log_path


def build_backup_path(path: Path) -> Path:
    timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir: Path = path.parent
    if backup_dir.name != BACKUP_DIRECTORY_NAME:
        backup_dir = backup_dir / BACKUP_DIRECTORY_NAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path: Path = backup_dir / f"{path.stem}.{timestamp}.bak{path.suffix}"
    LOGGER.debug("Backup path resolved to %s", backup_path)
    return backup_path


def create_backup(path: Path) -> Path:
    backup_path: Path = build_backup_path(path)
    shutil.copy2(path, backup_path)
    return backup_path


def read_text(path: Path) -> str:
    LOGGER.debug("Reading text from %s", path)
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    LOGGER.debug("Writing %d characters to %s", len(content), path)
    path.write_text(content, encoding="utf-8", newline="\n")
