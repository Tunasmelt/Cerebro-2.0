"""Stage 7.5 — stalled-upload expiry sweep + normalize/extract retry path.

Two gaps closed:
1. sweep_stalled_uploads (SupabaseDocumentsStorage, called from
   list_documents): a job stuck at ingest_jobs.state='uploading' past
   UPLOAD_STALL_EXPIRY_SECONDS gets swept to `failed` automatically —
   tested here against a fake httpx transport, same pattern as
   test_stage_3_6_document_storage.py.
2. retry_ingest's route dispatch: check_retry_eligible's resume stage
   (see test_retry_ingest.py for that function's own unit tests) now
   picks the right background pipeline — _embed_then_place,
   _run_ingest_pipeline, or _run_capture_pipeline.
"""
import json as _json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import BackgroundTasks

from app.core.documents_storage import SupabaseDocumentsStorage
from app.routes import documents as documents_module

# --- sweep_stalled_uploads -----------------------------------------------


class _SweepTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, stale_jobs: list[dict]):
        self.stale_jobs = stale_jobs
        self.ingest_jobs_patch_calls: list[dict] = []
        self.documents_patch_calls: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if path == "/rest/v1/ingest_jobs" and request.method == "GET":
            return httpx.Response(200, json=self.stale_jobs)
        if path == "/rest/v1/ingest_jobs" and request.method == "PATCH":
            self.ingest_jobs_patch_calls.append(params)
            return httpx.Response(204)
        if path == "/rest/v1/documents" and request.method == "PATCH":
            self.documents_patch_calls.append(
                {"params": params, "body": _json.loads(request.content)}
            )
            return httpx.Response(204)
        if path == "/rest/v1/documents" and request.method == "GET":
            return httpx.Response(200, json=[])

        raise AssertionError(f"unexpected {request.method} {path}")


def _patch_client(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


@pytest.mark.asyncio
async def test_sweep_marks_stale_uploading_jobs_and_documents_as_failed(monkeypatch):
    transport = _SweepTransport(
        stale_jobs=[{"document_id": "doc-1"}, {"document_id": "doc-2"}]
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    await storage.sweep_stalled_uploads(user_jwt="t", user_id="u")

    assert len(transport.ingest_jobs_patch_calls) == 1
    assert len(transport.documents_patch_calls) == 1
    doc_patch = transport.documents_patch_calls[0]
    assert doc_patch["body"] == {"status": "failed"}
    assert doc_patch["params"]["id"] == "in.(doc-1,doc-2)"


@pytest.mark.asyncio
async def test_sweep_does_nothing_when_no_stale_jobs_exist(monkeypatch):
    transport = _SweepTransport(stale_jobs=[])
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    await storage.sweep_stalled_uploads(user_jwt="t", user_id="u")

    assert transport.ingest_jobs_patch_calls == []
    assert transport.documents_patch_calls == []


@pytest.mark.asyncio
async def test_sweep_failure_is_swallowed_not_raised(monkeypatch):
    class _BrokenTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("simulated network failure")

    _patch_client(monkeypatch, _BrokenTransport())
    storage = SupabaseDocumentsStorage()

    # Must not raise — a sweep failure can never break document listing.
    await storage.sweep_stalled_uploads(user_jwt="t", user_id="u")


@pytest.mark.asyncio
async def test_list_documents_triggers_the_sweep_first(monkeypatch):
    transport = _SweepTransport(stale_jobs=[{"document_id": "doc-1"}])
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    await storage.list_documents(user_jwt="t", user_id="u")

    assert len(transport.ingest_jobs_patch_calls) == 1


# --- retry_ingest route dispatch ------------------------------------------


class _FakeRequest:
    def __init__(self, *, user_jwt: str, sub: str):
        self.state = SimpleNamespace(user_jwt=user_jwt, user={"sub": sub})


@pytest.mark.asyncio
async def test_retry_route_schedules_embed_then_place_when_embedding(monkeypatch):
    async def fake_check(*, user_jwt, document_id):
        return "embedding"

    monkeypatch.setattr(documents_module, "check_retry_eligible", fake_check)
    background_tasks = BackgroundTasks()

    response = await documents_module.retry_ingest(
        _FakeRequest(user_jwt="t", sub="u"), "doc-1", background_tasks
    )

    assert response.status_code == 202
    assert _json.loads(response.body)["state"] == "embedding"
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].func is documents_module._embed_then_place


@pytest.mark.asyncio
async def test_retry_route_schedules_full_pipeline_when_normalizing(monkeypatch):
    async def fake_check(*, user_jwt, document_id):
        return "normalizing"

    monkeypatch.setattr(documents_module, "check_retry_eligible", fake_check)
    background_tasks = BackgroundTasks()

    response = await documents_module.retry_ingest(
        _FakeRequest(user_jwt="t", sub="u"), "doc-2", background_tasks
    )

    assert response.status_code == 202
    assert _json.loads(response.body)["state"] == "normalizing"
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].func is documents_module._run_ingest_pipeline


@pytest.mark.asyncio
async def test_retry_route_schedules_capture_pipeline_when_extracting(monkeypatch):
    async def fake_check(*, user_jwt, document_id):
        return "extracting"

    monkeypatch.setattr(documents_module, "check_retry_eligible", fake_check)
    background_tasks = BackgroundTasks()

    response = await documents_module.retry_ingest(
        _FakeRequest(user_jwt="t", sub="u"), "doc-3", background_tasks
    )

    assert response.status_code == 202
    assert _json.loads(response.body)["state"] == "extracting"
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].func is documents_module._run_capture_pipeline


@pytest.mark.asyncio
async def test_retry_route_returns_error_status_from_retry_error(monkeypatch):
    from app.ingest.embed import RetryError

    async def fake_check(*, user_jwt, document_id):
        raise RetryError("not_found", "No ingest job found for this document")

    monkeypatch.setattr(documents_module, "check_retry_eligible", fake_check)
    background_tasks = BackgroundTasks()

    response = await documents_module.retry_ingest(
        _FakeRequest(user_jwt="t", sub="u"), "doc-4", background_tasks
    )

    assert response.status_code == 404
    assert background_tasks.tasks == []
