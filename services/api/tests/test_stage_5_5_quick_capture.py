"""Stage 5.5 — quick capture (journaling as ingest).

Route-level tests (fake DocumentsStorage seam, same pattern as
test_documents_list.py) prove the FastAPI wiring: validation (empty
text, oversized text), auth, and that a real background pipeline task
is scheduled. Storage-level tests (fake httpx transport, same pattern
as test_stage_3_6_document_storage.py) prove SupabaseDocumentsStorage's
real create_capture wiring: a documents row with source='capture' and
the raw text in captured_text, an ingest_jobs row starting at
'extracting' (not 'uploading'), no Storage call of any kind. The
extract.py half (source == "capture" skips any storage download) is
covered in test_stage_1_3_extract.py, right next to every other
run_extract_job branch.
"""
import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core import documents_storage as storage_module
from app.core.documents_storage import MAX_CAPTURE_CHARS, SupabaseDocumentsStorage
from app.ingest import embed as embed_module
from app.ingest import extract as extract_module
from app.main import app

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"
TEST_SUB = "11111111-1111-1111-1111-111111111111"


class _StubJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._key)


class _FakeDocumentsStorage:
    def __init__(self):
        self.last_capture_call: dict | None = None
        self.document_id_to_return = "doc-1"

    async def create_capture(self, *, user_jwt, user_id, title, text):
        self.last_capture_call = {"user_id": user_id, "title": title, "text": text}
        return self.document_id_to_return


class _NoOpExtractStorage:
    """Route-level tests exercise POST /documents/capture through the
    real FastAPI app, which schedules _run_capture_pipeline as a real
    BackgroundTask — and TestClient runs background tasks synchronously
    as part of the request, so without this seam the real
    SupabaseExtractStorage singleton would fire a real httpx call.
    Same no-op pattern test_stage_1_1_upload.py already established for
    exactly this reason."""

    async def get_document(self, *, user_jwt, document_id):
        return {
            "user_id": TEST_SUB,
            "mime": "text/plain",
            "source": "capture",
            "captured_text": "",
            "storage_path": "unused",
            "original_storage_path": "unused",
        }

    async def download_indexed(self, *, user_jwt, path):
        return b""

    async def download_original(self, *, user_jwt, path):
        return b""

    async def insert_chunks(self, **kwargs):
        pass

    async def mark_extracted(self, **kwargs):
        pass

    async def mark_failed(self, **kwargs):
        pass


class _NoOpEmbedStorage:
    """Empty captured_text -> zero chunks -> extract succeeds and chains
    into embed too; this keeps that leg off the real singleton as well."""

    async def get_document(self, *, user_jwt, document_id):
        return {"user_id": TEST_SUB, "mime": "text/plain", "original_storage_path": "unused"}

    async def get_chunks(self, *, user_jwt, document_id):
        return []

    async def download_original(self, *, user_jwt, path):
        return b""

    async def get_checkpoint(self, *, user_jwt, document_id):
        return {}

    async def save_checkpoint(self, **kwargs):
        pass

    async def update_chunk_embedding(self, **kwargs):
        pass

    async def mark_ready(self, **kwargs):
        pass

    async def mark_failed(self, **kwargs):
        pass


@pytest.fixture
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture
def documents_storage():
    return _FakeDocumentsStorage()


@pytest.fixture(autouse=True)
def _wire_test_seams(keypair, documents_storage, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    storage_module.set_documents_storage(documents_storage)
    extract_module.set_extract_storage(_NoOpExtractStorage())
    embed_module.set_embed_storage(_NoOpEmbedStorage())
    yield
    auth_module.set_jwks_client(None)
    storage_module.set_documents_storage(storage_module.SupabaseDocumentsStorage())
    extract_module.set_extract_storage(extract_module.SupabaseExtractStorage())
    embed_module.set_embed_storage(embed_module.SupabaseEmbedStorage())


@pytest.fixture
def client():
    return TestClient(app)


def auth_headers(private_key, sub=TEST_SUB):
    payload = {
        "iss": TEST_ISSUER,
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    return {"Authorization": f"Bearer {token}"}


# --- route-level ---------------------------------------------------------------


def test_capture_happy_path(client, keypair, documents_storage):
    private_key, _ = keypair
    response = client.post(
        "/api/v1/documents/capture",
        headers=auth_headers(private_key),
        json={"text": "remember to check the RRF_K constant"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "doc-1"
    assert body["state"] == "extracting"
    assert documents_storage.last_capture_call["text"] == "remember to check the RRF_K constant"
    assert documents_storage.last_capture_call["title"] == "remember to check the RRF_K constant"


def test_capture_derives_a_truncated_title_when_none_given(client, keypair, documents_storage):
    private_key, _ = keypair
    long_text = "a" * 100
    client.post(
        "/api/v1/documents/capture",
        headers=auth_headers(private_key),
        json={"text": long_text},
    )
    assert documents_storage.last_capture_call["title"] == ("a" * 60 + "…")


def test_capture_uses_explicit_title_when_given(client, keypair, documents_storage):
    private_key, _ = keypair
    client.post(
        "/api/v1/documents/capture",
        headers=auth_headers(private_key),
        json={"text": "some thought", "title": "My real title"},
    )
    assert documents_storage.last_capture_call["title"] == "My real title"


def test_capture_rejects_empty_text(client, keypair, documents_storage):
    private_key, _ = keypair
    response = client.post(
        "/api/v1/documents/capture",
        headers=auth_headers(private_key),
        json={"text": "   "},
    )
    assert response.status_code == 422
    assert documents_storage.last_capture_call is None


def test_capture_rejects_text_over_the_length_cap(client, keypair, documents_storage):
    private_key, _ = keypair
    response = client.post(
        "/api/v1/documents/capture",
        headers=auth_headers(private_key),
        json={"text": "a" * (MAX_CAPTURE_CHARS + 1)},
    )
    assert response.status_code == 413
    assert documents_storage.last_capture_call is None


def test_capture_requires_auth(client):
    response = client.post("/api/v1/documents/capture", json={"text": "hi"})
    assert response.status_code == 401


# --- storage-level (real SupabaseDocumentsStorage.create_capture) --------------


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.document_inserts: list[dict] = []
        self.job_inserts: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import json as _json

        path = request.url.path
        if path == "/rest/v1/documents" and request.method == "POST":
            body = _json.loads(request.content)
            self.document_inserts.append(body)
            return httpx.Response(201, json=[{**body, "id": "real-doc-1"}])
        if path == "/rest/v1/ingest_jobs" and request.method == "POST":
            body = _json.loads(request.content)
            self.job_inserts.append(body)
            return httpx.Response(201, json=[{**body, "id": "job-1"}])
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
async def test_create_capture_inserts_a_capture_document_and_an_extracting_job(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    document_id = await storage.create_capture(
        user_jwt="t", user_id="u1", title="a thought", text="the actual captured text"
    )

    assert document_id == "real-doc-1"
    assert len(transport.document_inserts) == 1
    doc_body = transport.document_inserts[0]
    assert doc_body["source"] == "capture"
    assert doc_body["captured_text"] == "the actual captured text"
    assert doc_body["mime"] == "text/plain"
    assert doc_body["status"] == "processing"
    assert doc_body["size_bytes"] == len(b"the actual captured text")

    assert len(transport.job_inserts) == 1
    job_body = transport.job_inserts[0]
    assert job_body["document_id"] == "real-doc-1"
    # Starts at 'extracting', not 'uploading' — normalize is genuinely
    # skipped for this source type, not just fast-pathed through.
    assert job_body["state"] == "extracting"
