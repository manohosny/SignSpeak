import io
import json
import logging

import pytest

from app.core.logging import (
    JsonFormatter,
    bind_context,
    clear_context,
    setup_logging,
    time_stage,
)


def _capture_stream() -> tuple[logging.Logger, io.StringIO]:
    """Build a logger that writes to an in-memory stream with the JSON formatter."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(f"test.{id(stream)}")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, stream


def test_json_formatter_emits_required_fields() -> None:
    logger, stream = _capture_stream()
    logger.info("hello")
    payload = json.loads(stream.getvalue().strip())
    assert payload["msg"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == logger.name
    assert "ts" in payload


def test_bind_context_propagates_to_records() -> None:
    logger, stream = _capture_stream()
    token = bind_context(meeting_id="m-42", user_id="u-7")
    try:
        logger.info("ping")
    finally:
        clear_context(token)
    payload = json.loads(stream.getvalue().strip())
    assert payload["meeting_id"] == "m-42"
    assert payload["user_id"] == "u-7"


def test_clear_context_resets_to_prior_state() -> None:
    logger, stream = _capture_stream()
    token = bind_context(meeting_id="m-1")
    clear_context(token)
    logger.info("ping")
    payload = json.loads(stream.getvalue().strip())
    assert "meeting_id" not in payload


def test_extra_kwargs_merged_into_payload() -> None:
    logger, stream = _capture_stream()
    logger.info("event", extra={"stage": "stt", "duration_ms": 12.5})
    payload = json.loads(stream.getvalue().strip())
    assert payload["stage"] == "stt"
    assert payload["duration_ms"] == 12.5


def test_time_stage_emits_done_with_duration() -> None:
    logger, stream = _capture_stream()
    with time_stage("stt", logger=logger, source="utterance_end"):
        pass
    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert payload["msg"] == "stage_done"
    assert payload["stage"] == "stt"
    assert payload["source"] == "utterance_end"
    assert "duration_ms" in payload
    assert payload["duration_ms"] >= 0


def test_time_stage_emits_failed_on_exception() -> None:
    logger, stream = _capture_stream()
    with pytest.raises(RuntimeError), time_stage("translation", logger=logger):
        raise RuntimeError("boom")
    line = stream.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["msg"] == "stage_failed"
    assert payload["stage"] == "translation"
    assert "duration_ms" in payload
    assert "exc" in payload


def test_setup_logging_text_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOG_FORMAT=text should install a non-JSON formatter."""
    monkeypatch.setenv("LOG_FORMAT", "text")
    setup_logging()
    handler = logging.getLogger().handlers[0]
    # Sanity check: emitted output is not JSON.
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname="", lineno=0,
        msg="hi", args=(), exc_info=None,
    )
    out = handler.formatter.format(record) if handler.formatter else ""
    assert not out.startswith("{")
    # Re-install JSON for the rest of the test session.
    monkeypatch.setenv("LOG_FORMAT", "json")
    setup_logging()
