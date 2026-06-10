"""Structured (JSON) logging with contextvar-based correlation.

Usage:

    from app.core.logging import setup_logging, bind_context, time_stage

    setup_logging()                          # call once at app start
    bind_context(request_id="abc123")        # adds the field to every record
    with time_stage("stt", meeting_id=...):  # emits start/end with duration_ms
        await stt_engine.transcribe(audio)

Goals:
- Zero new third-party deps (stdlib only).
- Per-record fields propagated via contextvars so async tasks inherit context.
- Cheap to no-op when JSON output is disabled (LOG_FORMAT=text).
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# Per-task correlation context. Async tasks inherit the current copy of the
# contextvar at creation time, so binding once on the WS connect or HTTP
# request entry propagates through downstream awaits.
_log_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    # Read-only default: callers only ever .get() it then .set() a fresh dict
    # (see bind/reset below), so the shared {} is never mutated in place.
    "_log_context",
    default={},  # noqa: B039
)

_RESERVED_RECORD_FIELDS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Formats records as single-line JSON with merged context."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%f"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        ctx = _log_context.get()
        if ctx:
            payload.update(ctx)

        # Merge any `extra=` kwargs the caller passed.
        for k, v in record.__dict__.items():
            if k in _RESERVED_RECORD_FIELDS or k.startswith("_"):
                continue
            payload[k] = v

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_logging(level: str | int | None = None) -> None:
    """Install the JSON formatter on the root logger.

    Honors LOG_FORMAT=text to keep human-readable output during local
    development, and LOG_LEVEL to override the threshold.
    """
    fmt = os.getenv("LOG_FORMAT", "json").lower()
    log_level = level or os.getenv("LOG_LEVEL", "INFO").upper()

    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s — %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root = logging.getLogger()
    # Replace existing handlers so we don't double-log when uvicorn or pytest
    # has already attached its own.
    root.handlers[:] = [handler]
    root.setLevel(log_level)


def bind_context(**fields: Any) -> contextvars.Token[dict[str, Any]]:
    """Add fields to the current context. Returns a token for resetting."""
    current = _log_context.get()
    merged = {**current, **fields}
    return _log_context.set(merged)


def clear_context(token: contextvars.Token[dict[str, Any]] | None = None) -> None:
    """Reset to the prior context (or empty if no token given)."""
    if token is not None:
        _log_context.reset(token)
    else:
        _log_context.set({})


@contextmanager
def time_stage(
    stage: str,
    logger: logging.Logger | None = None,
    **extra: Any,
) -> Iterator[None]:
    """Emit a `stage` log line on entry/exit with millisecond duration.

    On exception, logs at ERROR with the same shape plus an exc field.
    """
    log = logger or logging.getLogger("app.ml")
    log.debug("stage_start", extra={"stage": stage, **extra})
    start = time.perf_counter()
    try:
        yield
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        log.error(
            "stage_failed",
            extra={"stage": stage, "duration_ms": round(duration_ms, 2), **extra},
            exc_info=True,
        )
        raise
    else:
        duration_ms = (time.perf_counter() - start) * 1000
        log.info(
            "stage_done",
            extra={"stage": stage, "duration_ms": round(duration_ms, 2), **extra},
        )
