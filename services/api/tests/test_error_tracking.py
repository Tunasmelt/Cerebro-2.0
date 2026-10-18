"""init_error_tracking() — Sentry wiring, fails open with no DSN.

Tests the function directly with a monkeypatched sentry_sdk.init spy,
same posture as test_single_process_guard.py: this is pure
os.environ-branching logic, not worth a real network call or a fresh
app.main import.
"""
from unittest.mock import MagicMock

from app.core.error_tracking import init_error_tracking


def test_noop_with_no_dsn_set(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    spy = MagicMock()
    monkeypatch.setattr("app.core.error_tracking.sentry_sdk.init", spy)
    init_error_tracking()
    spy.assert_not_called()


def test_noop_with_blank_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "")
    spy = MagicMock()
    monkeypatch.setattr("app.core.error_tracking.sentry_sdk.init", spy)
    init_error_tracking()
    spy.assert_not_called()


def test_initializes_with_dsn_set(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://key@o0.ingest.sentry.io/0")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
    monkeypatch.delenv("BUILD_SHA", raising=False)
    spy = MagicMock()
    monkeypatch.setattr("app.core.error_tracking.sentry_sdk.init", spy)

    init_error_tracking()

    spy.assert_called_once_with(
        dsn="https://key@o0.ingest.sentry.io/0",
        environment="staging",
        release="abc123",
        traces_sample_rate=0,
    )


def test_defaults_environment_and_release_when_unset(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://key@o0.ingest.sentry.io/0")
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("BUILD_SHA", raising=False)
    spy = MagicMock()
    monkeypatch.setattr("app.core.error_tracking.sentry_sdk.init", spy)

    init_error_tracking()

    spy.assert_called_once_with(
        dsn="https://key@o0.ingest.sentry.io/0",
        environment="production",
        release="dev",
        traces_sample_rate=0,
    )
