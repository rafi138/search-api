"""Centralized logging — JSON structured output (ISO 8601 UTC timestamps).

Each log line is a single-line JSON object, recognized by ELK, Datadog,
CloudWatch, Splunk, and other log aggregators.
"""
import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Emit each log record as a one-line JSON object."""

    _EXTRA = ("method", "path", "status", "duration_ms", "client_ip")

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in self._EXTRA:
            if key in record.__dict__:
                entry[key] = record.__dict__[key]
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON output and silence noisy libraries."""
    log_level = getattr(logging, (level or "INFO").upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)

    for name in ("elasticsearch", "elastic_transport", "urllib3",
                 "aiohttp", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
