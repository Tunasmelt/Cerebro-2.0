"""Stage 7.4 — mem_watchdog RSS instrumentation.

Exit criteria: architecture-and-security.md §3 documented "Log RSS
before/after each ingest stage" as existing; nothing did. mem_watchdog.py
adds real logging, and routes/documents.py's pipeline wrappers
(_run_ingest_pipeline, _run_capture_pipeline, _embed_then_place) bracket
every stage call with it.

Tests: a seeded run through the wrapper functions produces start/end log
lines for every stage it touches, in the right order, and a stage that
raises still leaves its `end` line on record (the whole point — a crash
must still be traceable).
"""
import logging

import pytest

from app.ingest import mem_watchdog
from app.ingest.mem_watchdog import track_rss
from app.routes import documents as documents_module

LOGGER_NAME = "app.ingest.mem_watchdog"


def test_current_rss_mb_returns_a_positive_number_on_this_platform():
    # resource.getrusage exists on POSIX (Render/CI Linux runners);
    # on Windows dev this legitimately returns None — either is fine,
    # what matters is it never raises.
    value = mem_watchdog.current_rss_mb()
    assert value is None or value > 0


def test_track_rss_logs_start_and_end_lines_around_the_wrapped_code(caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        with track_rss(stage="normalize", document_id="doc-1"):
            pass

    messages = [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]
    if mem_watchdog.resource is None:
        assert messages == []  # non-POSIX dev machine — nothing to assert
        return

    assert len(messages) == 2
    assert "phase=start" in messages[0]
    assert "stage=normalize" in messages[0]
    assert "document_id=doc-1" in messages[0]
    assert "phase=end" in messages[1]
    assert "delta_mb=" in messages[1]


def test_track_rss_still_logs_end_when_the_wrapped_code_raises(caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        with pytest.raises(ValueError):
            with track_rss(stage="extract", document_id="doc-2"):
                raise ValueError("simulated stage failure")

    if mem_watchdog.resource is None:
        return

    messages = [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]
    assert any("phase=end" in m and "stage=extract" in m for m in messages)


@pytest.mark.asyncio
async def test_ingest_pipeline_brackets_every_stage_with_rss_logs(monkeypatch, caplog):
    async def fake_normalize(*, user_jwt, document_id):
        return True

    async def fake_extract(*, user_jwt, document_id):
        return True

    async def fake_embed(*, user_jwt, document_id):
        return True

    async def fake_place(*, user_jwt, user_id, document_id):
        return None

    monkeypatch.setattr(documents_module, "run_normalize_job", fake_normalize)
    monkeypatch.setattr(documents_module, "run_extract_job", fake_extract)
    monkeypatch.setattr(documents_module, "run_embed_job", fake_embed)
    monkeypatch.setattr(documents_module, "place_new_document", fake_place)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await documents_module._run_ingest_pipeline(
            user_jwt="t", user_id="u", document_id="doc-3"
        )

    if mem_watchdog.resource is None:
        return

    stages_logged = [
        r.getMessage().split("stage=")[1].split(" ")[0]
        for r in caplog.records
        if r.name == LOGGER_NAME and "phase=start" in r.getMessage()
    ]
    assert stages_logged == ["normalize", "extract", "embed"]


@pytest.mark.asyncio
async def test_ingest_pipeline_stops_after_failed_stage_with_no_further_rss_logs(
    monkeypatch, caplog
):
    async def failing_normalize(*, user_jwt, document_id):
        return False

    async def unexpected_extract(*, user_jwt, document_id):
        raise AssertionError("extract must not run after normalize failed")

    monkeypatch.setattr(documents_module, "run_normalize_job", failing_normalize)
    monkeypatch.setattr(documents_module, "run_extract_job", unexpected_extract)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await documents_module._run_ingest_pipeline(
            user_jwt="t", user_id="u", document_id="doc-4"
        )

    if mem_watchdog.resource is None:
        return

    stages_logged = {
        r.getMessage().split("stage=")[1].split(" ")[0]
        for r in caplog.records
        if r.name == LOGGER_NAME
    }
    assert stages_logged == {"normalize"}
