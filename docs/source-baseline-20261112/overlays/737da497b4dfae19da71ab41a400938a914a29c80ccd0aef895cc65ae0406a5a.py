"""Structured JSON logging for V4.

Provides a lightweight JSON formatter and a setup helper so every application
log line is emitted as a machine-readable record (ts, level, logger, message)
instead of free-form text. Audit queries can then filter by level and timestamp
without parsing prose.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key in ("run_id", "workload_id", "trade_date", "stage_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def setup_json_logging(*, level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def log_boundary(
    logger: logging.Logger,
    *,
    level: int,
    message: str,
    run_id: str | None = None,
    workload_id: str | None = None,
    trade_date: str | None = None,
    stage_id: str | None = None,
) -> None:
    """Emit a structured boundary event (e.g. BUY gate denied) with extra keys."""
    extras: dict[str, str] = {}
    if run_id:
        extras["run_id"] = run_id
    if workload_id:
        extras["workload_id"] = workload_id
    if trade_date:
        extras["trade_date"] = trade_date
    if stage_id:
        extras["stage_id"] = stage_id
    logger.log(level, message, extra=extras)


__all__ = ["JsonFormatter", "log_boundary", "setup_json_logging"]
