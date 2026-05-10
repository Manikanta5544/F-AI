"""
Structured logging configuration using structlog.

Development: pretty-printed, colorised output.
Production:  JSON output — one line per event, compatible with Datadog / ELK.

Call configure_logging() once at startup (in main.py lifespan).
"""
from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import settings


def configure_logging() -> None:
    """Configure structlog and stdlib logging for the environment."""

    shared_processors: list = [
        structlog.stdlib.filter_by_level,
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.ENVIRONMENT == "production":
        # JSON output — machine readable
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Pretty-print with colours for local development
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.DEBUG else logging.INFO
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),  
        cache_logger_on_first_use=True,
    )

    # Redirect stdlib logging through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
    )

    # Quiet noisy third-party loggers
    for noisy in ("httpx", "uvicorn.access", "sqlalchemy.engine", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)