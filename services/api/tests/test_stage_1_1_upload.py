"""Stage 1.1 — upload & storage split.

Exit criteria: files upload to `originals`, size-capped at 50MB, rejected
cleanly above that.

FastAPI-side tests use a fake DocumentsStorage (test seam) so they're
deterministic and don't need live Supabase network calls — same pattern as
Stages 0.5/0.6. A live check against the real deployed stack (proxy +
Render + Supabase) is run manually and reported in the conversation record,
since the doc's own test explicitly wants network-level proof for the
oversized-upload-never-reaches-Render case, which only a live proxy proves.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core import documents_storage as storage_module
from app.core.documents_storage import MAX_UPLOAD_BYTES, UploadedDocument
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
        self.uploaded = []
        self.inserted = []

    async def upload_original(self, *, user_jwt, user_id, document_id, ext, content, mime):
        self.uploaded.append((user_id, document_id, ext, len(content), mime))
        return f"{user_id}/{document_id}/original.{ext}"

    async def insert_document(
        self, *, user_jwt, user_id, document_id, title, mime, size_bytes, original_storage_path
    ):
        self.inserted.append((user_id, document_id, title, mime, size_bytes))
        return UploadedDocument(
            id=document_id,
            title=title,
            mime=mime,
            size_bytes=size_bytes,
            original_storage_path=original_storage_path,
            status="processing",
        )


@pytest.fixture
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture
def fake_storage():
    return _FakeDocumentsStorage()


@pytest.fixture(autouse=True)
def _wire_test_seams(keypair, fake_storage, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    storage_module.set_documents_storage(fake_storage)
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


def test_upload_under_cap_succeeds_and_appears_in_originals(client, keypair, fake_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    response = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("hello.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "processing"
    assert body["original_storage_path"] == f"{TEST_SUB}/{body['id']}/original.txt"
    assert len(fake_storage.uploaded) == 1
    assert fake_storage.uploaded[0][0] == TEST_SUB


def test_upload_over_cap_rejected_cleanly(client, keypair, fake_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    oversized = b"x" * (MAX_UPLOAD_BYTES + 1)
    response = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("big.txt", oversized, "text/plain")},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert len(fake_storage.uploaded) == 0


def test_disallowed_mime_type_rejected_cleanly_not_500(client, keypair, fake_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    response = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("script.exe", b"MZ\x90\x00", "application/x-msdownload")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_mime_type"
    assert len(fake_storage.uploaded) == 0


def test_upload_requires_auth(client):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("hello.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 401
