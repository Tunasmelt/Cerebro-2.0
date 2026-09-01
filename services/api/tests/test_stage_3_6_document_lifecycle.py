"""Stage 3.6 — document lifecycle completion: single fetch, download,
original, delete. Found by a post-Phase-3-gate audit of
api-documentation.md against the real routes — GET /documents/{id},
GET /documents/{id}/download, GET /documents/{id}/original, and
DELETE /documents/{id} were documented in Phase 1's spec but never
built.

Exit criteria: single-document fetch scoped to the caller (404 for
another user's document, RLS); download/original return signed URLs for
the caller's own document but a SEALED document rejects both with 423
rather than a signed URL (the load-bearing test in this file — sealing
never re-encrypted the underlying Storage object, so this is the first
route that could otherwise bypass the passphrase entirely); delete
removes both Storage objects and the documents row.

Same fake-storage seam pattern as test_documents_list.py.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core import documents_storage as storage_module
from app.core.documents_storage import DocumentsStorageError
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
        self.document_to_return: dict | None = None
        self.signed_url_to_return: str | None = None
        self.signed_url_error: DocumentsStorageError | None = None
        self.delete_result: bool = True
        self.signed_url_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []

    async def list_documents(self, *, user_jwt, user_id):
        return []

    async def get_document(self, *, user_jwt, document_id):
        return self.document_to_return

    async def get_signed_url(self, *, user_jwt, document_id, variant):
        self.signed_url_calls.append((document_id, variant))
        if self.signed_url_error:
            raise self.signed_url_error
        return self.signed_url_to_return

    async def delete_document(self, *, user_jwt, document_id):
        self.delete_calls.append(document_id)
        return self.delete_result


@pytest.fixture
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture(autouse=True)
def _wire_test_seams(keypair, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    yield
    auth_module.set_jwks_client(None)
    storage_module.set_documents_storage(storage_module.SupabaseDocumentsStorage())


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


# --- GET /documents/{id} -----------------------------------------------------


def test_get_document_returns_metadata_and_ingest_state(client, keypair):
    private_key, _ = keypair
    fake = _FakeDocumentsStorage()
    fake.document_to_return = {
        "id": "doc-1",
        "title": "notes.txt",
        "status": "ready",
        "ingest_state": "ready",
        "last_error": None,
    }
    storage_module.set_documents_storage(fake)

    response = client.get("/api/v1/documents/doc-1", headers=auth_headers(private_key))

    assert response.status_code == 200
    assert response.json() == fake.document_to_return


def test_get_document_not_found_returns_404(client, keypair):
    private_key, _ = keypair
    fake = _FakeDocumentsStorage()
    fake.document_to_return = None
    storage_module.set_documents_storage(fake)

    response = client.get("/api/v1/documents/doc-missing", headers=auth_headers(private_key))
    assert response.status_code == 404


def test_get_document_requires_auth(client):
    storage_module.set_documents_storage(_FakeDocumentsStorage())
    assert client.get("/api/v1/documents/doc-1").status_code == 401


# --- GET /documents/{id}/download and /original ------------------------------


def test_download_returns_signed_url(client, keypair):
    private_key, _ = keypair
    fake = _FakeDocumentsStorage()
    fake.signed_url_to_return = "https://example.supabase.co/storage/v1/object/sign/indexed/x?token=abc"
    storage_module.set_documents_storage(fake)

    response = client.get("/api/v1/documents/doc-1/download", headers=auth_headers(private_key))

    assert response.status_code == 200
    assert response.json() == {"url": fake.signed_url_to_return}
    assert fake.signed_url_calls == [("doc-1", "indexed")]


def test_original_returns_signed_url(client, keypair):
    private_key, _ = keypair
    fake = _FakeDocumentsStorage()
    fake.signed_url_to_return = "https://example.supabase.co/storage/v1/object/sign/originals/x?token=abc"
    storage_module.set_documents_storage(fake)

    response = client.get("/api/v1/documents/doc-1/original", headers=auth_headers(private_key))

    assert response.status_code == 200
    assert fake.signed_url_calls == [("doc-1", "original")]


def test_download_of_sealed_document_returns_423_never_a_url(client, keypair):
    """The load-bearing test for this stage: a sealed document must
    never yield a signed URL through either route — sealing (Stage 3.3)
    only ever removed plaintext from `chunks`, never touched the
    Storage object, so a signed URL here would be a straight bypass of
    the passphrase."""
    private_key, _ = keypair
    fake = _FakeDocumentsStorage()
    fake.signed_url_error = DocumentsStorageError(
        "document_sealed", "This document is sealed and cannot be downloaded"
    )
    storage_module.set_documents_storage(fake)

    response = client.get("/api/v1/documents/doc-1/download", headers=auth_headers(private_key))
    assert response.status_code == 423
    assert response.json()["error"]["code"] == "document_sealed"
    assert "url" not in response.json()


def test_original_of_sealed_document_returns_423_never_a_url(client, keypair):
    private_key, _ = keypair
    fake = _FakeDocumentsStorage()
    fake.signed_url_error = DocumentsStorageError(
        "document_sealed", "This document is sealed and cannot be downloaded"
    )
    storage_module.set_documents_storage(fake)

    response = client.get("/api/v1/documents/doc-1/original", headers=auth_headers(private_key))
    assert response.status_code == 423
    assert response.json()["error"]["code"] == "document_sealed"
    assert "url" not in response.json()


def test_download_not_found_returns_404(client, keypair):
    private_key, _ = keypair
    fake = _FakeDocumentsStorage()
    fake.signed_url_error = DocumentsStorageError("not_found", "Document not found")
    storage_module.set_documents_storage(fake)

    response = client.get("/api/v1/documents/doc-missing/download", headers=auth_headers(private_key))
    assert response.status_code == 404


def test_download_requires_auth(client):
    storage_module.set_documents_storage(_FakeDocumentsStorage())
    assert client.get("/api/v1/documents/doc-1/download").status_code == 401


def test_original_requires_auth(client):
    storage_module.set_documents_storage(_FakeDocumentsStorage())
    assert client.get("/api/v1/documents/doc-1/original").status_code == 401


# --- DELETE /documents/{id} ---------------------------------------------------


def test_delete_document_succeeds(client, keypair):
    private_key, _ = keypair
    fake = _FakeDocumentsStorage()
    fake.delete_result = True
    storage_module.set_documents_storage(fake)

    response = client.delete("/api/v1/documents/doc-1", headers=auth_headers(private_key))

    assert response.status_code == 200
    assert response.json() == {"id": "doc-1", "deleted": True}
    assert fake.delete_calls == ["doc-1"]


def test_delete_document_not_found_returns_404(client, keypair):
    private_key, _ = keypair
    fake = _FakeDocumentsStorage()
    fake.delete_result = False
    storage_module.set_documents_storage(fake)

    response = client.delete("/api/v1/documents/doc-missing", headers=auth_headers(private_key))
    assert response.status_code == 404


def test_delete_document_requires_auth(client):
    storage_module.set_documents_storage(_FakeDocumentsStorage())
    assert client.delete("/api/v1/documents/doc-1").status_code == 401


# --- Sealed documents can still be deleted (deletion needs ownership, --------
# --- not the passphrase) -------------------------------------------------------


def test_sealed_document_can_still_be_deleted(client, keypair):
    private_key, _ = keypair
    fake = _FakeDocumentsStorage()
    fake.delete_result = True  # storage doesn't special-case sealed docs for delete
    storage_module.set_documents_storage(fake)

    response = client.delete("/api/v1/documents/doc-1", headers=auth_headers(private_key))
    assert response.status_code == 200
