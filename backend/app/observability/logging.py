"""Structured JSON logging. Every log line is one JSON object with a UTC ISO timestamp."""

import logging
import sys
from typing import Any

import structlog


class _StderrLogger:
    """Writes to whatever `sys.stderr` is at write time. (A stream bound at configuration time
    breaks once it is replaced and closed, e.g. by test output capture.)"""

    def msg(self, message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    log = debug = info = warning = warn = error = critical = exception = fatal = msg


def _stderr_logger(*args: Any) -> _StderrLogger:
    return _StderrLogger()


def configure_logging(level: str = "INFO") -> None:
    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=numeric_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=_stderr_logger,
        cache_logger_on_first_use=False,
    )


def get_logger(name: str, **initial: Any) -> structlog.typing.FilteringBoundLogger:
    logger: structlog.typing.FilteringBoundLogger = structlog.get_logger(name, **initial)
    return logger
