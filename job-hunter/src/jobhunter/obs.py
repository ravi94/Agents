"""Observability: structured tracing, log rotation, and error signalling.

Implements Constitution Principle VIII with the standard library only (no hosted
service, no metered cost — Principles II/VI):

- **Run correlation id.** :func:`configure_run_logging` mints a run id and threads
  it into every log line via a filter, so one run's activity is isolable end to end.
- **Rotation.** Logs go to a size-rotated file under the app data directory
  (``logs/jobhunter.log``), so the local footprint stays bounded.
- **Tracing.** :func:`trace` wraps an LLM/external call and records its operation,
  source, outcome, and duration — **metadata only**, never resume/prefs payloads.
- **Monitoring.** :func:`notify_error` pushes an error signal to ntfy when a topic is
  configured (``JOBHUNTER_NTFY_TOPIC``); it is a best-effort no-op otherwise and
  never lets a failed notification crash the run.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
import uuid
from logging.handlers import RotatingFileHandler

from jobhunter import config

_LOGGER_NAME = "jobhunter"
_DEFAULT_MAX_BYTES = 1_000_000
_DEFAULT_BACKUP_COUNT = 5
_NTFY_TOPIC_ENV = "JOBHUNTER_NTFY_TOPIC"

# The run id current traces/log lines are stamped with; set per run by
# configure_run_logging(). "-" until a run is configured (e.g. library use).
_current_run_id = "-"

# Never emit a "no handlers" warning when used as a library before a run is
# configured; the real rotating handler is attached by configure_run_logging().
logging.getLogger(_LOGGER_NAME).addHandler(logging.NullHandler())


class _RunIdFilter(logging.Filter):
    """Injects the active run id onto every record so the formatter can show it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _current_run_id
        return True


def new_run_id() -> str:
    """Return a short, unique run correlation id."""
    return uuid.uuid4().hex[:12]


def current_run_id() -> str:
    """Return the active run's correlation id (the one every log line carries).

    ``"-"`` if no run has been configured yet (e.g. library use outside the
    CLI). Callers that mint their own id instead of using this one produce a
    result that can't be grepped out of the log by the id it's shown under.
    """
    return _current_run_id


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the jobhunter logger (or a named child of it)."""
    return logging.getLogger(_LOGGER_NAME if not name else f"{_LOGGER_NAME}.{name}")


def configure_run_logging(
    run_id: str | None = None,
    *,
    level: int = logging.INFO,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
) -> str:
    """Attach a rotating file handler for this run and return its run id.

    Idempotent across runs in one process: any prior rotating handler is closed
    and replaced, so handlers never stack (e.g. across tests or CLI invocations).
    """
    global _current_run_id
    _current_run_id = run_id or new_run_id()

    root = get_logger()
    for handler in list(root.handlers):
        if isinstance(handler, RotatingFileHandler):
            root.removeHandler(handler)
            handler.close()

    log_file = config.log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.addFilter(_RunIdFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [run=%(run_id)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level)
    return _current_run_id


@contextlib.contextmanager
def trace(operation: str, *, source: str | None = None, logger: logging.Logger | None = None):
    """Trace an LLM/external call: log start, then outcome + duration.

    Records metadata only. On failure the exception *type* is logged (never its
    message, which may carry payload text) and the exception is re-raised.
    """
    log = logger or get_logger("trace")
    src = f" source={source}" if source else ""
    start = time.monotonic()
    log.info("start %s%s", operation, src)
    try:
        yield
    except BaseException as exc:  # noqa: BLE001 — log then re-raise, don't swallow
        duration_ms = (time.monotonic() - start) * 1000
        log.error(
            "fail %s%s duration_ms=%.0f error=%s", operation, src, duration_ms, type(exc).__name__
        )
        raise
    else:
        duration_ms = (time.monotonic() - start) * 1000
        log.info("ok %s%s duration_ms=%.0f", operation, src, duration_ms)


def _post(url: str, data: bytes) -> None:
    """POST raw bytes to ``url`` (stdlib only). Isolated for test seams."""
    import urllib.request

    request = urllib.request.Request(url, data=data, method="POST")
    urllib.request.urlopen(request, timeout=5)  # noqa: S310 — fixed https ntfy endpoint


def notify(message: str, *, topic_env: str = _NTFY_TOPIC_ENV) -> bool:
    """Push a notification to ntfy if a topic is configured; best-effort.

    Returns True if a notification was sent. A missing topic is a no-op (False),
    and a failed post is logged and swallowed (False) — monitoring must never
    become a new failure mode. Shared by the error path (`notify_error`) and
    the alerting path (`scoring/alert.py`) — one notification channel
    (research.md §5), just different callers/content.
    """
    topic = os.environ.get(topic_env)
    if not topic:
        return False
    try:
        _post(f"https://ntfy.sh/{topic}", message.encode("utf-8"))
        return True
    except Exception:  # noqa: BLE001 — notification is best-effort
        get_logger("obs").warning("ntfy notification failed")
        return False


def notify_error(message: str, *, topic_env: str = _NTFY_TOPIC_ENV) -> bool:
    """Push an error signal to ntfy if a topic is configured; best-effort."""
    return notify(message, topic_env=topic_env)
