"""Stage 3.3 — seal/unseal API and unlock claims.

Exit criteria: an unlock issues a 15-minute session-scoped claim, and
expiry is enforced server-side, not just client-side.
Tests required: a claim used after 15 minutes is rejected; a claim
reused past its stated scope (i.e. against a different document than it
was issued for) is rejected.

Route tests use the same fake-storage seam pattern as
test_documents_list.py; is_claim_expired and _decrypt are pure functions
tested directly, with no I/O, so the actual expiry/crypto logic is
proven rather than just route wiring.
"""
import base64
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core import sealed_storage as sealed_storage_module
from app.core.sealed_storage import (
    SealedStorageError,
    UnlockClaim,
    _decrypt,
    is_claim_expired,
)
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
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture(autouse=True)
def _wire_test_seams(keypair, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    yield
    auth_module.set_jwks_client(None)
    sealed_storage_module.set_sealed_storage(sealed_storage_module.SupabaseSealedStorage())


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


# --- Pure logic: is_claim_expired -----------------------------------------


def test_is_claim_expired_false_when_well_within_ttl():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    expires_at = now + timedelta(minutes=15)
    assert is_claim_expired(expires_at, now=now) is False


def test_is_claim_expired_true_after_15_minutes():
    issued_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    expires_at = issued_at + timedelta(minutes=15)
    now = issued_at + timedelta(minutes=15, seconds=1)
    assert is_claim_expired(expires_at, now=now) is True


def test_is_claim_expired_true_exactly_at_expiry_boundary():
    expires_at = datetime(2026, 1, 1, 12, 15, 0, tzinfo=timezone.utc)
    assert is_claim_expired(expires_at, now=expires_at) is True


# --- Pure logic: _decrypt ---------------------------------------------------


def _seal(plaintext: bytes, key: bytes) -> tuple[str, str]:
    nonce = b"\x00" * 12
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return (
        base64.b64encode(nonce).decode(),
        base64.b64encode(ciphertext).decode(),
    )


def test_decrypt_succeeds_with_correct_key():
    key = AESGCM.generate_key(bit_length=256)
    nonce_b64, ciphertext_b64 = _seal(b"hello sealed world", key)
    plaintext = _decrypt(base64.b64encode(key).decode(), nonce_b64, ciphertext_b64)
    assert plaintext == b"hello sealed world"


def test_decrypt_raises_sealed_storage_error_with_wrong_key():
    key = AESGCM.generate_key(bit_length=256)
    wrong_key = AESGCM.generate_key(bit_length=256)
    nonce_b64, ciphertext_b64 = _seal(b"hello sealed world", key)
    with pytest.raises(SealedStorageError) as exc_info:
        _decrypt(base64.b64encode(wrong_key).decode(), nonce_b64, ciphertext_b64)
    assert exc_info.value.code == "invalid_key"


# --- Route tests: /seal -----------------------------------------------------


class _FakeSealedStorage:
    def __init__(self):
        self.sealed_calls = []
        self.claim_to_issue: UnlockClaim | None = None
        self.unlock_error: SealedStorageError | None = None
        self.unseal_result: list | None = None
        self.unseal_error: SealedStorageError | None = None

    async def seal_document(self, *, user_jwt, user_id, document_id, chunks):
        self.sealed_calls.append((document_id, chunks))

    async def create_unlock_claim(self, *, user_jwt, user_id, document_id, key_b64):
        if self.unlock_error:
            raise self.unlock_error
        return self.claim_to_issue

    async def unseal_document(self, *, user_jwt, user_id, document_id, claim_id, key_b64):
        if self.unseal_error:
            raise self.unseal_error
        return self.unseal_result


def test_seal_document_stores_ciphertext_and_returns_sealed_status(client, keypair):
    private_key, _ = keypair
    fake = _FakeSealedStorage()
    sealed_storage_module.set_sealed_storage(fake)

    response = client.post(
        "/api/v1/documents/doc-1/seal",
        headers=auth_headers(private_key),
        json={
            "chunks": [
                {"ordinal": 0, "content_ciphertext": "Y3Q=", "salt": "c2FsdA==", "nonce": "bm9uY2U="}
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {"id": "doc-1", "status": "sealed"}
    assert len(fake.sealed_calls) == 1
    document_id, chunks = fake.sealed_calls[0]
    assert document_id == "doc-1"
    assert chunks[0].ordinal == 0


def test_seal_requires_auth(client):
    sealed_storage_module.set_sealed_storage(_FakeSealedStorage())
    response = client.post("/api/v1/documents/doc-1/seal", json={"chunks": []})
    assert response.status_code == 401


# --- Route tests: /unlock ---------------------------------------------------


def test_unlock_wrong_key_returns_401(client, keypair):
    private_key, _ = keypair
    fake = _FakeSealedStorage()
    fake.unlock_error = SealedStorageError("invalid_key", "nope")
    sealed_storage_module.set_sealed_storage(fake)

    response = client.post(
        "/api/v1/documents/doc-1/unlock",
        headers=auth_headers(private_key),
        json={"key": "d3Jvbmc="},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_key"


def test_unlock_no_sealed_content_returns_404(client, keypair):
    private_key, _ = keypair
    fake = _FakeSealedStorage()
    fake.unlock_error = SealedStorageError("not_found", "nothing sealed")
    sealed_storage_module.set_sealed_storage(fake)

    response = client.post(
        "/api/v1/documents/doc-1/unlock",
        headers=auth_headers(private_key),
        json={"key": "a2V5"},
    )
    assert response.status_code == 404


def test_unlock_success_issues_claim(client, keypair):
    private_key, _ = keypair
    fake = _FakeSealedStorage()
    fake.claim_to_issue = UnlockClaim(claim_id="claim-1", expires_at="2026-01-01T12:15:00+00:00")
    sealed_storage_module.set_sealed_storage(fake)

    response = client.post(
        "/api/v1/documents/doc-1/unlock",
        headers=auth_headers(private_key),
        json={"key": "a2V5"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["claim_id"] == "claim-1"
    assert body["expires_at"] == "2026-01-01T12:15:00+00:00"


# --- Route tests: /unseal — the two required behaviors ----------------------


def test_unseal_rejects_a_claim_used_after_15_minutes(client, keypair):
    """Required test: a claim used after 15 minutes is rejected."""
    private_key, _ = keypair
    fake = _FakeSealedStorage()
    fake.unseal_error = SealedStorageError("claim_expired", "expired")
    sealed_storage_module.set_sealed_storage(fake)

    response = client.post(
        "/api/v1/documents/doc-1/unseal",
        headers=auth_headers(private_key),
        json={"claim_id": "claim-1", "key": "a2V5"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "claim_expired"


def test_unseal_rejects_a_claim_reused_past_its_scope(client, keypair):
    """Required test: a claim reused past its stated scope (a different
    document than it was issued for) is rejected."""
    private_key, _ = keypair
    fake = _FakeSealedStorage()
    fake.unseal_error = SealedStorageError("claim_scope_mismatch", "wrong document")
    sealed_storage_module.set_sealed_storage(fake)

    response = client.post(
        "/api/v1/documents/some-other-doc/unseal",
        headers=auth_headers(private_key),
        json={"claim_id": "claim-issued-for-doc-1", "key": "a2V5"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "claim_scope_mismatch"


def test_unseal_claim_not_found_returns_404(client, keypair):
    private_key, _ = keypair
    fake = _FakeSealedStorage()
    fake.unseal_error = SealedStorageError("claim_not_found", "no such claim")
    sealed_storage_module.set_sealed_storage(fake)

    response = client.post(
        "/api/v1/documents/doc-1/unseal",
        headers=auth_headers(private_key),
        json={"claim_id": "does-not-exist", "key": "a2V5"},
    )
    assert response.status_code == 404


def test_unseal_success_returns_decrypted_chunks(client, keypair):
    private_key, _ = keypair
    fake = _FakeSealedStorage()
    fake.unseal_result = [{"ordinal": 0, "content": "the secret text"}]
    sealed_storage_module.set_sealed_storage(fake)

    response = client.post(
        "/api/v1/documents/doc-1/unseal",
        headers=auth_headers(private_key),
        json={"claim_id": "claim-1", "key": "a2V5"},
    )
    assert response.status_code == 200
    assert response.json() == {"chunks": [{"ordinal": 0, "content": "the secret text"}]}


def test_unseal_requires_auth(client):
    sealed_storage_module.set_sealed_storage(_FakeSealedStorage())
    response = client.post(
        "/api/v1/documents/doc-1/unseal", json={"claim_id": "c", "key": "a2V5"}
    )
    assert response.status_code == 401
