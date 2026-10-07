"""Structured logging.

JSON lines in production so the platform log viewer and Vigil can filter on
fields. Optional fields are read with getattr/hasattr only: referencing a
custom field in a %-format string is what raised inside the logging module
during the Groq outage and hid the real error for two days.
"""
import json
import logging
from collections import deque
from datetime import datetime, timezone
from threading import Lock

EXTRA_FIELDS = (
    "request_id", "org_id", "user_id", "latency_ms", "status_code", "endpoint",
    "method", "provider", "model", "fallback", "fallback_reason", "doc_id", "job_id",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in EXTRA_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class RecentLogBuffer(logging.Handler):
    """Keeps the last N WARNING+ records in memory for GET /metrics/logs."""

    def __init__(self, capacity: int = 500):
        super().__init__(level=logging.WARNING)
        self._records: deque[dict] = deque(maxlen=capacity)
        self._lock = Lock()
        self._formatter = JsonFormatter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = json.loads(self._formatter.format(record))
        except Exception:  # noqa: BLE001 — a logging handler must never raise
            return
        with self._lock:
            self._records.append(entry)

    def snapshot(self, since: str | None = None, level: str | None = None, contains: str | None = None,
                 limit: int = 100) -> list[dict]:
        with self._lock:
            rows = list(self._records)
        if since:
            rows = [r for r in rows if r["ts"] >= since]
        if level:
            floor = logging.getLevelName(level.upper())
            if isinstance(floor, int):
                rows = [r for r in rows if logging.getLevelName(r["level"]) >= floor]
        if contains:
            needle = contains.lower()
            rows = [r for r in rows if needle in json.dumps(r).lower()]
        return rows[-limit:]


recent_logs = RecentLogBuffer()


def configure_logging(json_logs: bool) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter() if json_logs else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler, recent_logs], force=True)
