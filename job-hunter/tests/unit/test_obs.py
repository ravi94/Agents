"""Tests for the observability module (obs.py) — Constitution Principle VIII.

Covers the three non-negotiables: a run correlation id threaded into every log
line, a rotating log file under the app data dir, call tracing that records
metadata only (never payloads), and an ntfy error signal that is a no-op unless
a topic is configured. Written first (Principle VII) — expected to fail until
obs.py exists.
"""

import logging
from logging.handlers import RotatingFileHandler

import pytest

from jobhunter import config, obs


def _flush() -> None:
    for handler in logging.getLogger("jobhunter").handlers:
        handler.flush()


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNTER_HOME", str(tmp_path))
    yield
    # Drop the rotating handler this test added so handlers don't stack.
    root = logging.getLogger("jobhunter")
    for handler in list(root.handlers):
        if isinstance(handler, RotatingFileHandler):
            root.removeHandler(handler)
            handler.close()


def test_new_run_id_is_unique():
    assert obs.new_run_id() != obs.new_run_id()


def test_configure_writes_rotating_log_with_run_id():
    run_id = obs.configure_run_logging()

    obs.get_logger("test").info("hello world")
    _flush()

    log_file = config.log_path()
    assert log_file.exists()
    contents = log_file.read_text()
    assert run_id in contents
    assert "hello world" in contents

    root = logging.getLogger("jobhunter")
    assert any(isinstance(h, RotatingFileHandler) for h in root.handlers)


def test_trace_logs_success_with_duration_and_source():
    obs.configure_run_logging()

    with obs.trace("llm.structure_resume", source="claude_cli"):
        pass
    _flush()

    contents = config.log_path().read_text()
    assert "llm.structure_resume" in contents
    assert "claude_cli" in contents
    assert "duration_ms" in contents


def test_trace_logs_failure_metadata_only_and_reraises():
    obs.configure_run_logging()

    with pytest.raises(ValueError):
        with obs.trace("llm.structure_resume"):
            raise ValueError("boom SECRET-RESUME-PAYLOAD")
    _flush()

    contents = config.log_path().read_text()
    assert "llm.structure_resume" in contents
    # Metadata only: the exception TYPE is logged, never the message payload.
    assert "ValueError" in contents
    assert "SECRET-RESUME-PAYLOAD" not in contents


def test_notify_error_is_noop_without_topic(monkeypatch):
    monkeypatch.delenv("JOBHUNTER_NTFY_TOPIC", raising=False)
    assert obs.notify_error("something failed") is False


def test_notify_error_posts_when_topic_set(monkeypatch):
    monkeypatch.setenv("JOBHUNTER_NTFY_TOPIC", "my-topic")
    sent = {}

    def fake_post(url, data):
        sent["url"] = url
        sent["data"] = data

    monkeypatch.setattr(obs, "_post", fake_post)

    assert obs.notify_error("boom") is True
    assert "my-topic" in sent["url"]


def test_notify_error_swallows_post_failure(monkeypatch):
    monkeypatch.setenv("JOBHUNTER_NTFY_TOPIC", "my-topic")

    def boom(url, data):
        raise OSError("network down")

    monkeypatch.setattr(obs, "_post", boom)

    # A failed notification must never crash the run.
    assert obs.notify_error("boom") is False


# T023 [P] [US3] — obs.notify: generalized alert path, mirrors notify_error above.
# Expected to fail until T024 adds obs.notify.
def test_notify_is_noop_without_topic(monkeypatch):
    monkeypatch.delenv("JOBHUNTER_NTFY_TOPIC", raising=False)
    assert obs.notify("something to say") is False


def test_notify_posts_when_topic_set(monkeypatch):
    monkeypatch.setenv("JOBHUNTER_NTFY_TOPIC", "my-topic")
    sent = {}

    def fake_post(url, data):
        sent["url"] = url
        sent["data"] = data

    monkeypatch.setattr(obs, "_post", fake_post)

    assert obs.notify("new match found") is True
    assert "my-topic" in sent["url"]


def test_notify_swallows_post_failure(monkeypatch):
    monkeypatch.setenv("JOBHUNTER_NTFY_TOPIC", "my-topic")

    def boom(url, data):
        raise OSError("network down")

    monkeypatch.setattr(obs, "_post", boom)

    # A failed notification must never crash the run.
    assert obs.notify("new match found") is False
