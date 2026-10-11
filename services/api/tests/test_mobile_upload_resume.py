"""Renewal must preserve identity and never authorize another owner's object."""

import json

import httpx
import pytest
from fastapi import HTTPException

from app.core.documents_storage import SupabaseDocumentsStorage


@pytest.mark.asyncio
async def test_confirm_is_idempotent_after_response_loss(monkeypatch):
    job = {"state": "uploading", "last_error": None}
    doc = {
        "user_id": "owner",
        "status": "processing",
        "size_bytes": 0,
        "original_storage_path": "owner/doc/original.txt",
    }
    storage_reads = []

    def handle(request):
        if request.url.path == "/rest/v1/documents":
            if request.method == "GET":
                return httpx.Response(200, json=[doc])
            doc.update(json.loads(request.content))
            return httpx.Response(204)
        if request.url.path == "/rest/v1/ingest_jobs":
            if request.method == "GET":
                return httpx.Response(200, json=[job.copy()])
            assert request.url.params["state"] == "eq.uploading"
            job.update(json.loads(request.content))
            return httpx.Response(200, json=[job.copy()])
        assert request.url.path == "/storage/v1/object/list/originals"
        storage_reads.append(request)
        return httpx.Response(
            200, json=[{"name": "original.txt", "metadata": {"size": 11}}]
        )

    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    storage = SupabaseDocumentsStorage()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(storage, "_client", lambda: client)
        first = await storage.confirm(
            user_jwt="owner-jwt", user_id="owner", document_id="doc"
        )
        job["state"] = "ready"
        doc["status"] = "ready"
        repeated = await storage.confirm(
            user_jwt="owner-jwt", user_id="owner", document_id="doc"
        )
    assert first.started is True
    assert repeated.started is False
    assert repeated.state == "ready"
    assert len(storage_reads) == 1
    assert job["state"] == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,error", [("uploading", None), ("failed", "upload_expired")]
)
async def test_resume_renews_same_object_without_creating_rows(
    monkeypatch, state, error
):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer owner-jwt"
        if request.url.path == "/rest/v1/documents":
            if request.method == "PATCH":
                assert json.loads(request.content)["status"] == "processing"
                return httpx.Response(204)
            assert request.method == "GET"
            return httpx.Response(
                200,
                json=[
                    {
                        "user_id": "owner",
                        "status": "failed" if state == "failed" else "processing",
                        "original_storage_path": "owner/doc/original.txt",
                    }
                ],
            )
        if request.url.path == "/rest/v1/ingest_jobs":
            if request.method == "GET":
                return httpx.Response(200, json=[{"state": state, "last_error": error}])
            assert request.method == "PATCH"
            assert request.url.params["state"] == f"eq.{state}"
            if state == "failed":
                assert request.url.params["last_error"] == "eq.upload_expired"
            assert json.loads(request.content)["state"] == "uploading"
            return httpx.Response(200, json=[{"state": "uploading"}])
        assert (
            request.url.path
            == "/storage/v1/object/upload/sign/originals/owner/doc/original.txt"
        )
        assert json.loads(request.content) == {}
        return httpx.Response(
            200,
            json={
                "url": "/object/upload/sign/originals/owner/doc/original.txt?token=fresh"
            },
        )

    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    storage = SupabaseDocumentsStorage()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(storage, "_client", lambda: client)
        result = await storage.resume_upload(
            user_jwt="owner-jwt", user_id="owner", document_id="doc"
        )
    assert result.document_id == "doc"
    assert result.upload_url.endswith("?token=fresh")
    assert len(calls) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "document,job,status",
    [
        (None, None, 404),
        ({"user_id": "other", "status": "processing"}, None, 404),
        ({"user_id": "owner", "status": "sealed"}, None, 409),
        ({"user_id": "owner", "status": "ready"}, None, 409),
        ({"user_id": "owner", "status": "processing"}, {"state": "embedding"}, 409),
        (
            {"user_id": "owner", "status": "processing"},
            {"state": "failed", "last_error": "file_too_large"},
            409,
        ),
        (
            {
                "user_id": "owner",
                "status": "processing",
                "original_storage_path": "other/doc/original.txt",
            },
            {"state": "uploading"},
            409,
        ),
        (
            {
                "user_id": "owner",
                "status": "processing",
                "original_storage_path": "owner/doc/../original.txt",
            },
            {"state": "uploading"},
            409,
        ),
        ({"user_id": "owner", "status": "processing"}, None, 409),
    ],
)
async def test_unrecoverable_or_cross_owner_never_signs(
    monkeypatch, document, job, status
):
    def handle(request):
        assert request.method == "GET", "No signing or mutation on a rejected resume"
        rows = (
            [document]
            if request.url.path.endswith("documents") and document
            else [job]
            if job
            else []
        )
        return httpx.Response(200, json=rows)

    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    storage = SupabaseDocumentsStorage()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(storage, "_client", lambda: client)
        with pytest.raises(HTTPException) as caught:
            await storage.resume_upload(
                user_jwt="owner-jwt", user_id="owner", document_id="doc"
            )
    assert caught.value.status_code == status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failed_path,status",
    [
        ("/rest/v1/ingest_jobs", 502),
        ("/storage/v1/object/upload/sign/originals/owner/doc/original.txt", 502),
        ("patch_job", 502),
        ("concurrent_confirm", 409),
    ],
)
async def test_resume_failures_do_not_return_authorization(
    monkeypatch, failed_path, status
):
    def handle(request):
        path = request.url.path
        if path == failed_path:
            return httpx.Response(503)
        if path == "/rest/v1/documents":
            return httpx.Response(
                200,
                json=[
                    {
                        "user_id": "owner",
                        "status": "processing",
                        "original_storage_path": "owner/doc/original.txt",
                    }
                ],
            )
        if path == "/rest/v1/ingest_jobs":
            if request.method == "GET":
                return httpx.Response(
                    200, json=[{"state": "uploading", "last_error": None}]
                )
            if failed_path == "patch_job":
                return httpx.Response(503)
            if failed_path == "concurrent_confirm":
                return httpx.Response(200, json=[])
            raise AssertionError("Unexpected job mutation")
        return httpx.Response(200, json={"url": "/signed?token=fresh"})

    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    storage = SupabaseDocumentsStorage()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(storage, "_client", lambda: client)
        with pytest.raises(HTTPException) as caught:
            await storage.resume_upload(
                user_jwt="owner-jwt", user_id="owner", document_id="doc"
            )
    assert caught.value.status_code == status


@pytest.mark.asyncio
@pytest.mark.parametrize("status,rows", [(200, []), (500, [])])
async def test_sweep_does_not_fail_documents_when_expiry_did_not_win(monkeypatch, status, rows):
    def handle(request):
        assert request.url.path == "/rest/v1/ingest_jobs", "Renewed documents must not be marked failed"
        if request.method == "GET":
            return httpx.Response(200, json=[{"document_id": "doc"}])
        assert request.headers["prefer"] == "return=representation"
        assert request.url.params["state"] == "eq.uploading"
        assert "created_at" in request.url.params
        return httpx.Response(status, json=rows)

    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    storage = SupabaseDocumentsStorage()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(storage, "_client", lambda: client)
        await storage.sweep_stalled_uploads(user_jwt="owner-jwt", user_id="owner")


@pytest.mark.asyncio
async def test_upload_transitions_serialize_across_storage_instances(monkeypatch):
    import asyncio

    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def handle(request):
        calls.append(request)
        if len(calls) == 1:
            entered.set()
            await release.wait()
        return httpx.Response(200, json=[])

    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    first, second = SupabaseDocumentsStorage(), SupabaseDocumentsStorage()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(first, "_client", lambda: client)
        monkeypatch.setattr(second, "_client", lambda: client)
        sweep = asyncio.create_task(first.sweep_stalled_uploads(user_jwt="jwt", user_id="owner"))
        await entered.wait()
        resume = asyncio.create_task(second.resume_upload(user_jwt="jwt", user_id="owner", document_id="doc"))
        confirm = asyncio.create_task(second.confirm(user_jwt="jwt", user_id="owner", document_id="doc"))
        await asyncio.sleep(0)
        assert len(calls) == 1, "Renewal/confirmation must wait for the full sweep"
        release.set()
        await sweep
        results = await asyncio.gather(resume, confirm, return_exceptions=True)
        assert all(isinstance(result, HTTPException) and result.status_code == 404 for result in results)
        assert len(calls) == 3
