import json

import pytest

from app.observability import configure_logging, get_logger


def test_logs_are_json_lines_with_utc_timestamps(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    get_logger("test", component="facts").info("facts.recomputed", store_id="s1")
    event = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert event["event"] == "facts.recomputed"
    assert event["level"] == "info"
    assert event["store_id"] == "s1"
    assert event["component"] == "facts"
    assert event["timestamp"].endswith("Z")


def test_level_filtering_and_unknown_level(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING")
    get_logger("test").info("hidden")
    assert capsys.readouterr().err == ""
    configure_logging("NOT-A-LEVEL")  # falls back to INFO
    get_logger("test").info("shown")
    assert "shown" in capsys.readouterr().err
