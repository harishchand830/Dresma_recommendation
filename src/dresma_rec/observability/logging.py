"""Structured JSON logging configuration."""

import logging
import sys

from pythonjsonlogger import jsonlogger

from dresma_rec.config.settings import get_settings


def setup_logging() -> None:
    """Configure root logger for JSON output to stdout (GCP Cloud Logging compatible)."""
    settings = get_settings()
    log_level = (
        logging.DEBUG if settings.environment == "development" else logging.INFO
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)
