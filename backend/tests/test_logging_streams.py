"""Logging keeps working after the stream it was configured with is replaced and closed."""

import io
import sys

import pytest

from app.observability import configure_logging, get_logger


def test_logging_survives_a_closed_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    first = io.StringIO()
    monkeypatch.setattr(sys, "stderr", first)
    configure_logging("INFO")
    log = get_logger("test")
    log.info("one")
    first.close()  # e.g. a captured stream at the end of a test
    second = io.StringIO()
    monkeypatch.setattr(sys, "stderr", second)
    log.info("two")
    log.warning("three")
    assert '"event": "two"' in second.getvalue()
    assert '"event": "three"' in second.getvalue()
