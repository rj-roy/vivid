"""Logging configuration and log tailing for diagnostics."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .paths import ensure_runtime_dirs, log_path

LOGGER_NAME = "vivid"


def setup_logging(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_vivid_configured", False):
        if verbose:
            logger.setLevel(logging.DEBUG)
        return logger
    ensure_runtime_dirs()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S"
    )
    try:
        handler = RotatingFileHandler(
            log_path(), maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    except OSError:
        pass
    if verbose:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.setLevel(logging.DEBUG)
        logger.addHandler(console)
    logger._vivid_configured = True  # type: ignore[attr-defined]
    return logger


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def tail_log(lines: int = 200) -> str:
    path = Path(log_path())
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"could not read log: {exc}"
    return "\n".join(content[-lines:])
