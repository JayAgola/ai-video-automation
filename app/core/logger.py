"""Structured logging with [TAG] prefixes required by spec.

Logs go to stdout AND to a persistent file (logs/pipeline.log) so the
dashboard log viewer can read them. This reuses Python's logging, extending
the existing StreamHandler setup with a RotatingFileHandler — not a second
logging system.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

_configured = False

# Simple timestamped format; the message itself carries the [TAG].
FILE_FMT = logging.Formatter(
    "%(asctime)sZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
STREAM_FMT = logging.Formatter("%(message)s")

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


def get_logger(name: str = "pipeline") -> logging.Logger:
    global _configured
    logger = logging.getLogger(name)
    if not _configured:
        logger.setLevel(logging.INFO)
        logger.propagate = False

        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(STREAM_FMT)
        logger.addHandler(stream)

        try:
            from app.core import config
            config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(str(config.LOG_FILE), maxBytes=2_000_000,
                                     backupCount=3, encoding="utf-8")
            fh.setFormatter(FILE_FMT)
            logger.addHandler(fh)
        except Exception:
            pass  # file logging is best-effort; stdout still works

        _configured = True
    return logger


def log(tag: str, msg: str, level: str = "INFO") -> None:
    lvl = LEVELS.get(str(level).upper(), 20)
    get_logger().log(lvl, "[%s] %s" % (tag, msg))
