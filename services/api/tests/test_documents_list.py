"""UI-implementation gap #1 (Phase 0-2 audit) — a Documents page needs
somewhere to list a user's documents; no such route existed anywhere,
despite api-documentation.md long describing one. Same fake-storage
seam pattern as test_stage_1_1_upload.py.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core import documents_storage as storage_module
from app.main import app

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"
TEST_SUB = "11111111-1111-1111-1111-111111111111"


class _StubJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._key)


class _FakeDocumentsStorage:
    def __init__(self, documents=None):
        self._documents = documents or []

    async def list_documents(self, *, user_jwt, user_id):
        return self._documents


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


def test_list_documents_returns_the_callers_documents(client, keypair):
    private_key, _ = keypair
    docs = [
        {
            "id": "doc-1",
            "title": "notes.txt",
            "mime": "text/plain",
            "size_bytes": 42,
            "status": "ready",
            "created_at": "2026-01-01T00:00:00Z",
        },
        {
            "id": "doc-2",
            "title": "paper.pdf",
            "mime": "application/pdf",
            "size_bytes": 900,
            "status": "processing",
            "created_at": "2026-01-02T00:00:00Z",
        },
    ]
    storage_module.set_documents_storage(_FakeDocumentsStorage(docs))

    response = client.get("/api/v1/documents", headers=auth_headers(private_key))

    assert response.status_code == 200
    assert response.json()["documents"] == docs


def test_list_documents_empty_when_none_uploaded(client, keypair):
    storage_module.set_documents_storage(_FakeDocumentsStorage([]))
    response = client.get("/api/v1/documents", headers=auth_headers(private_key=keypair[0]))
    assert response.status_code == 200
    assert response.json()["documents"] == []


def test_list_documents_requires_auth(client):
    storage_module.set_documents_storage(_FakeDocumentsStorage([]))
    assert client.get("/api/v1/documents").status_code == 401
