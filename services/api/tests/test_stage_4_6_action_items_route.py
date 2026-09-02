"""Route-level tests for Stage 4.6's POST
/documents/{id}/extract-action-items, mirroring
test_stage_3_6_document_lifecycle.py's TestClient pattern. The
extraction/parsing logic itself is covered by
test_stage_4_6_action_items.py; this proves the FastAPI wiring — auth
and the 404-not-403 not-owned case.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

import app.routes.documents as documents_routes_module
from app.core import auth as auth_module
from app.main import app

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"
TEST_SUB = "11111111-1111-1111-1111-111111111111"


class _StubJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._key)


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


def test_extract_action_items_happy_path(client, keypair, monkeypatch):
    private_key, _ = keypair

    async def fake_extract_action_items(*, user_jwt, document_id):
        assert document_id == "doc-1"
        return [{"title": "Send invoice", "description": "", "source_chunk_id": "c1"}]

    monkeypatch.setattr(
        documents_routes_module, "extract_action_items", fake_extract_action_items
    )

    response = client.post(
        "/api/v1/documents/doc-1/extract-action-items", headers=auth_headers(private_key)
    )
    assert response.status_code == 200
    assert response.json() == {
        "items": [{"title": "Send invoice", "description": "", "source_chunk_id": "c1"}]
    }


def test_extract_action_items_for_unowned_document_returns_404(client, keypair, monkeypatch):
    private_key, _ = keypair

    async def fake_extract_action_items(*, user_jwt, document_id):
        return None

    monkeypatch.setattr(
        documents_routes_module, "extract_action_items", fake_extract_action_items
    )

    response = client.post(
        "/api/v1/documents/does-not-exist/extract-action-items",
        headers=auth_headers(private_key),
    )
    assert response.status_code == 404


def test_extract_action_items_requires_auth(client):
    response = client.post("/api/v1/documents/doc-1/extract-action-items")
    assert response.status_code == 401
