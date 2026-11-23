"""Centralized logging configuration for VOLUMAX."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import LOGS_DIR


def setup_logging(level: str = "INFO", log_to_file: bool = True) -> logging.Logger:
    """Configure root logger and return the application logger."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Clear existing handlers to avoid duplicates on re-init
    for h in root.handlers[:]:
        root.removeHandler(h)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_to_file:
        file_handler = RotatingFileHandler(
            LOGS_DIR / "volumax.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    logger = logging.getLogger("volumax")
    logger.debug("Logging initialised (level=%s)", level)
    return logger


def get_logger(name: str = "volumax") -> logging.Logger:
    return logging.getLogger(name)
