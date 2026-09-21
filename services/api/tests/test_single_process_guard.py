"""Post-review hardening — main.py's single-process deployment guard.

The rate limiter and ingest lock are process-local (in-memory), so more
than one worker/instance would silently weaken rate limits and let two
ingest jobs run concurrently, with no error to catch it. Rather than
depend on operators remembering that constraint, main.py now fails
fast at import time if WEB_CONCURRENCY or CEREBRO_INSTANCE_COUNT ever
indicate more than one process — see architecture-and-security.md's
rate-limit section.

Tests the validation function directly rather than via a fresh import
of app.main: `_validate_single_process_deployment()` runs
unconditionally at module import time, so re-importing app.main to
exercise the raising path would also re-run that module's app/router
construction — unnecessary and fragile for what's actually pure
os.environ branching logic.
"""
import pytest

from app.main import _validate_single_process_deployment


def test_passes_with_no_env_vars_set(monkeypatch):
    # The documented default — Render's free tier, one process.
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.delenv("CEREBRO_INSTANCE_COUNT", raising=False)
    _validate_single_process_deployment()  # must not raise


def test_passes_when_both_explicitly_set_to_one(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    monkeypatch.setenv("CEREBRO_INSTANCE_COUNT", "1")
    _validate_single_process_deployment()  # must not raise


def test_raises_when_worker_count_is_scaled_up(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    monkeypatch.delenv("CEREBRO_INSTANCE_COUNT", raising=False)
    with pytest.raises(RuntimeError):
        _validate_single_process_deployment()


def test_raises_when_instance_count_is_scaled_up(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.setenv("CEREBRO_INSTANCE_COUNT", "3")
    with pytest.raises(RuntimeError):
        _validate_single_process_deployment()
