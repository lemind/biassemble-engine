import json
import time

import pytest
import structlog

from src.observability import (
    KEY_LATENCY_MS,
    KEY_REQUEST_ID,
    EVT_RETRIEVAL_STARTED,
    TimingContext,
    configure_logging,
)


@pytest.fixture(autouse=True)
def reset_structlog():
    """Reset structlog global state between tests to avoid cross-test interference."""
    yield
    structlog.reset_defaults()


# ── TimingContext ─────────────────────────────────────────────────────────────

def test_timing_context_elapsed_is_non_negative():
    with TimingContext() as t:
        pass
    assert t.elapsed_ms >= 0


def test_timing_context_elapsed_is_int():
    with TimingContext() as t:
        pass
    assert isinstance(t.elapsed_ms, int)


def test_timing_context_measures_elapsed():
    with TimingContext() as t:
        time.sleep(0.02)
    assert t.elapsed_ms >= 20


def test_timing_context_elapsed_available_after_exit():
    ctx = TimingContext()
    with ctx:
        pass
    assert ctx.elapsed_ms >= 0


# ── configure_logging / structlog output ─────────────────────────────────────

def test_json_log_contains_event_key(capsys):
    configure_logging("INFO")
    log = structlog.get_logger()
    log.info(EVT_RETRIEVAL_STARTED, **{KEY_REQUEST_ID: "req-1", KEY_LATENCY_MS: 0})
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["event"] == EVT_RETRIEVAL_STARTED


def test_json_log_contains_request_id(capsys):
    configure_logging("INFO")
    log = structlog.get_logger()
    log.info("test", **{KEY_REQUEST_ID: "req-abc", KEY_LATENCY_MS: 10})
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data[KEY_REQUEST_ID] == "req-abc"


def test_json_log_contains_latency_ms(capsys):
    configure_logging("INFO")
    log = structlog.get_logger()
    log.info("test", **{KEY_REQUEST_ID: "req-1", KEY_LATENCY_MS: 42})
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data[KEY_LATENCY_MS] == 42


def test_debug_mode_uses_console_renderer(capsys):
    configure_logging("DEBUG")
    log = structlog.get_logger()
    log.debug("hello", **{KEY_REQUEST_ID: "req-1"})
    out = capsys.readouterr().out
    # ConsoleRenderer output is not valid JSON
    assert out != ""
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(out)
