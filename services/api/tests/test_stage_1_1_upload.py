"""Stage 1.1 (revised) — upload & storage split via signed-URL
direct-to-storage flow.

Exit criteria: files upload to `originals` via signed-URL, size-capped at
50MB, rejected cleanly above that. See architecture-and-security.md §1
for why the flow is upload-init -> browser PUT -> upload-confirm, not a
proxy that receives the file bytes (Vercel hard-caps function bodies well
under 50MB, discovered when the original design was deployed and tested
live).

FastAPI-side tests use a fake DocumentsStorage (test seam) so they're
deterministic and don't need live Supabase network calls — same pattern
as Stages 0.5/0.6. The size/mime enforcement itself lives at Supabase
Storage's bucket-level config now (not in this code), and was verified
live against the real project — see the Stage 1.1 conversation record:
a direct 51MB PUT got a real EntityTooLarge/413, a disallowed mime got a
real InvalidMimeType/415, both from Supabase itself.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core import documents_storage as storage_module
from app.core.documents_storage import (
    MAX_UPLOAD_BYTES,
    ConfirmedUpload,
    SignedUpload,
)
from app.ingest import normalize as normalize_module
from app.main import app

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"
TEST_SUB = "11111111-1111-1111-1111-111111111111"
OTHER_SUB = "22222222-2222-2222-2222-222222222222"


class _StubJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._key)


class _FakeDocumentsStorage:
    def __init__(self):
        self.documents = {}  # document_id -> {"user_id":..., "size": int|None}
        self.authorized = []

    async def authorize(self, *, user_jwt, user_id, title, mime):
        document_id = f"doc-{len(self.documents) + 1}"
        self.documents[document_id] = {"user_id": user_id, "size": None}
        self.authorized.append((user_id, title, mime))
        return SignedUpload(
            document_id=document_id,
            upload_url=f"https://fake.supabase.co/upload/{document_id}",
        )

    async def confirm(self, *, user_jwt, user_id, document_id):
        doc = self.documents.get(document_id)
        if doc is None or doc["user_id"] != user_id:
            raise HTTPException(status_code=404, detail="document_not_found")
        if doc["size"] is None:
            raise HTTPException(status_code=422, detail="upload_not_found")
        if doc["size"] > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="file_too_large")
        return ConfirmedUpload(
            document_id=document_id, state="normalizing", size_bytes=doc["size"]
        )


class _NoOpNormalizeStorage:
    """upload-confirm fires a background normalize task (Stage 1.2) —
    this keeps it from making real network calls during Stage 1.1's
    tests, which only care about the confirm response itself."""

    async def get_document(self, *, user_jwt, document_id):
        return {
            "user_id": TEST_SUB,
            "mime": "text/plain",
            "original_storage_path": "unused",
        }

    async def download_original(self, *, user_jwt, path):
        return b""

    async def upload_indexed(self, **kwargs):
        return "unused"

    async def mark_normalized(self, **kwargs):
        pass

    async def mark_failed(self, **kwargs):
        pass


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
    normalize_module.set_normalize_storage(_NoOpNormalizeStorage())
    yield
    auth_module.set_jwks_client(None)
    storage_module.set_documents_storage(storage_module.SupabaseDocumentsStorage())
    normalize_module.set_normalize_storage(normalize_module.SupabaseNormalizeStorage())


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


def init_body(filename="hello.txt", mime="text/plain", size_bytes=42):
    return {"filename": filename, "mime": mime, "size_bytes": size_bytes}


def test_upload_init_under_cap_returns_signed_url(client, keypair, fake_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    response = client.post(
        "/api/v1/documents/upload-init", headers=headers, json=init_body()
    )
    assert response.status_code == 201
    body = response.json()
    assert "upload_url" in body
    assert fake_storage.authorized == [(TEST_SUB, "hello.txt", "text/plain")]


def test_disallowed_mime_type_rejected_before_signed_url_issued(client, keypair, fake_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    response = client.post(
        "/api/v1/documents/upload-init",
        headers=headers,
        json=init_body(filename="script.exe", mime="application/x-msdownload"),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_mime_type"
    assert fake_storage.authorized == []


def test_declared_oversized_size_rejected_before_signed_url_issued(client, keypair, fake_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    response = client.post(
        "/api/v1/documents/upload-init",
        headers=headers,
        json=init_body(size_bytes=MAX_UPLOAD_BYTES + 1),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert fake_storage.authorized == []


def test_confirm_after_real_upload_succeeds(client, keypair, fake_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    init = client.post(
        "/api/v1/documents/upload-init", headers=headers, json=init_body()
    ).json()
    fake_storage.documents[init["id"]]["size"] = 42  # simulates the real PUT happening

    response = client.post(f"/api/v1/documents/{init['id']}/upload-confirm", headers=headers)
    assert response.status_code == 200
    assert response.json()["state"] == "normalizing"
    assert response.json()["size_bytes"] == 42


def test_confirm_without_a_real_upload_is_rejected(client, keypair, fake_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    init = client.post(
        "/api/v1/documents/upload-init", headers=headers, json=init_body()
    ).json()
    # No PUT ever happened — confirm must not just trust the client's word.
    response = client.post(f"/api/v1/documents/{init['id']}/upload-confirm", headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "upload_not_found"


def test_confirm_rejects_an_oversized_object(client, keypair, fake_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    init = client.post(
        "/api/v1/documents/upload-init",
        headers=headers,
        json=init_body(filename="big.txt"),
    ).json()
    fake_storage.documents[init["id"]]["size"] = MAX_UPLOAD_BYTES + 1

    response = client.post(f"/api/v1/documents/{init['id']}/upload-confirm", headers=headers)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_confirm_on_another_users_document_returns_404_not_403(client, keypair, fake_storage):
    private_key, _ = keypair
    owner_headers = auth_headers(private_key, sub=TEST_SUB)
    other_headers = auth_headers(private_key, sub=OTHER_SUB)
    init = client.post(
        "/api/v1/documents/upload-init", headers=owner_headers, json=init_body()
    ).json()
    fake_storage.documents[init["id"]]["size"] = 10

    response = client.post(
        f"/api/v1/documents/{init['id']}/upload-confirm", headers=other_headers
    )
    assert response.status_code == 404


def test_upload_endpoints_require_auth(client):
    assert (
        client.post("/api/v1/documents/upload-init", json=init_body()).status_code
        == 401
    )
    assert (
        client.post("/api/v1/documents/doc-1/upload-confirm").status_code == 401
    )


def test_max_upload_bytes_is_binary_mib_not_decimal_mb():
    # Empirically pinned against the real Supabase bucket (see conversation
    # record): 52,428,800 bytes succeeds, 52,428,801 fails with
    # EntityTooLarge. Supabase's Free plan ceiling is binary MiB, not
    # decimal MB (50_000_000) — a unit mismatch here fails silently right
    # at the boundary since both numbers "look like 50MB". This must also
    # match supabase/migrations/0004_originals_bucket_limits.sql exactly.
    assert MAX_UPLOAD_BYTES == 52_428_800
    assert MAX_UPLOAD_BYTES == 50 * 1024 * 1024
    assert MAX_UPLOAD_BYTES != 50_000_000
