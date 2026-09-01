"""Stage 3.6 — storage-level tests for the real SupabaseDocumentsStorage
new methods (get_document, get_signed_url, delete_document), against a
fake httpx transport, same pattern as test_stage_2_5_storage.py /
test_stage_3_5_seal_storage.py. Route-level tests
(test_stage_3_6_document_lifecycle.py) only ever exercise a fake storage
seam — these prove the real HTTP wiring: the sealed-document rejection
happens before any Storage sign call, and delete removes both Storage
objects before the documents row.
"""
import json as _json

import httpx
import pytest

from app.core.documents_storage import DocumentsStorageError, SupabaseDocumentsStorage


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, document: dict | None, job: dict | None = None):
        self.document = document
        self.job = job
        self.sign_calls: list[str] = []
        self.storage_delete_calls: list[tuple[str, list[str]]] = []
        self.documents_delete_calls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if path == "/rest/v1/documents" and request.method == "GET":
            if self.document is None:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[self.document])

        if path == "/rest/v1/ingest_jobs" and request.method == "GET":
            return httpx.Response(200, json=[self.job] if self.job else [])

        if path.startswith("/storage/v1/object/sign/") and request.method == "POST":
            self.sign_calls.append(path)
            bucket = path.split("/")[-2]
            file_path = path.split("/")[-1]
            return httpx.Response(
                200, json={"signedURL": f"/object/sign/{bucket}/{file_path}?token=fake"}
            )

        if path == "/storage/v1/object/indexed" and request.method == "DELETE":
            body = _json.loads(request.content)
            self.storage_delete_calls.append(("indexed", body["prefixes"]))
            return httpx.Response(200, json={"message": "deleted"})

        if path == "/storage/v1/object/originals" and request.method == "DELETE":
            body = _json.loads(request.content)
            self.storage_delete_calls.append(("originals", body["prefixes"]))
            return httpx.Response(200, json={"message": "deleted"})

        if path == "/rest/v1/documents" and request.method == "DELETE":
            self.documents_delete_calls.append(params.get("id", ""))
            return httpx.Response(204)

        raise AssertionError(f"unexpected {request.method} {path}")


def _patch_client(monkeypatch, transport: _FakeTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


@pytest.mark.asyncio
async def test_get_document_merges_ingest_state_and_last_error(monkeypatch):
    transport = _FakeTransport(
        document={"id": "doc-1", "title": "x.txt", "status": "processing"},
        job={"state": "extracting", "last_error": None},
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    document = await storage.get_document(user_jwt="t", document_id="doc-1")

    assert document["ingest_state"] == "extracting"
    assert document["last_error"] is None


@pytest.mark.asyncio
async def test_get_document_returns_none_when_not_found(monkeypatch):
    transport = _FakeTransport(document=None)
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    document = await storage.get_document(user_jwt="t", document_id="doc-missing")
    assert document is None


@pytest.mark.asyncio
async def test_get_signed_url_signs_the_indexed_bucket_for_download(monkeypatch):
    transport = _FakeTransport(
        document={"id": "doc-1", "status": "ready", "storage_path": "u1/doc-1/indexed.txt"}
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    url = await storage.get_signed_url(user_jwt="t", document_id="doc-1", variant="indexed")

    assert transport.sign_calls == ["/storage/v1/object/sign/indexed/u1/doc-1/indexed.txt"]
    assert "indexed" in url


@pytest.mark.asyncio
async def test_get_signed_url_signs_the_originals_bucket_for_original(monkeypatch):
    transport = _FakeTransport(
        document={"id": "doc-1", "status": "ready", "original_storage_path": "u1/doc-1/original.txt"}
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    await storage.get_signed_url(user_jwt="t", document_id="doc-1", variant="original")

    assert transport.sign_calls == ["/storage/v1/object/sign/originals/u1/doc-1/original.txt"]


@pytest.mark.asyncio
async def test_get_signed_url_rejects_sealed_document_before_any_sign_call(monkeypatch):
    """The load-bearing assertion: no /storage/v1/object/sign call is
    ever made for a sealed document — the rejection happens before any
    network call that could produce a working signed URL."""
    transport = _FakeTransport(
        document={
            "id": "doc-1",
            "status": "sealed",
            "storage_path": "u1/doc-1/indexed.txt",
            "original_storage_path": "u1/doc-1/original.txt",
        }
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    with pytest.raises(DocumentsStorageError) as exc_info:
        await storage.get_signed_url(user_jwt="t", document_id="doc-1", variant="indexed")

    assert exc_info.value.code == "document_sealed"
    assert transport.sign_calls == []


@pytest.mark.asyncio
async def test_get_signed_url_not_found_raises_before_any_sign_call(monkeypatch):
    transport = _FakeTransport(document=None)
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    with pytest.raises(DocumentsStorageError) as exc_info:
        await storage.get_signed_url(user_jwt="t", document_id="doc-missing", variant="indexed")

    assert exc_info.value.code == "not_found"
    assert transport.sign_calls == []


@pytest.mark.asyncio
async def test_delete_document_removes_both_storage_objects_before_the_row(monkeypatch):
    transport = _FakeTransport(
        document={
            "id": "doc-1",
            "status": "ready",
            "storage_path": "u1/doc-1/indexed.txt",
            "original_storage_path": "u1/doc-1/original.txt",
        }
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    deleted = await storage.delete_document(user_jwt="t", document_id="doc-1")

    assert deleted is True
    assert ("indexed", ["u1/doc-1/indexed.txt"]) in transport.storage_delete_calls
    assert ("originals", ["u1/doc-1/original.txt"]) in transport.storage_delete_calls
    assert transport.documents_delete_calls == ["eq.doc-1"]


@pytest.mark.asyncio
async def test_delete_document_returns_false_when_not_found(monkeypatch):
    transport = _FakeTransport(document=None)
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    deleted = await storage.delete_document(user_jwt="t", document_id="doc-missing")

    assert deleted is False
    assert transport.storage_delete_calls == []
    assert transport.documents_delete_calls == []


@pytest.mark.asyncio
async def test_delete_document_works_on_a_sealed_document(monkeypatch):
    """Deletion needs ownership (RLS), not the passphrase — a sealed
    document is not specially rejected here, unlike get_signed_url."""
    transport = _FakeTransport(
        document={
            "id": "doc-1",
            "status": "sealed",
            "storage_path": "u1/doc-1/indexed.txt",
            "original_storage_path": "u1/doc-1/original.txt",
        }
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    deleted = await storage.delete_document(user_jwt="t", document_id="doc-1")
    assert deleted is True
