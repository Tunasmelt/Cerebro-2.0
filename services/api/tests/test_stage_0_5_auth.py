"""Stage 0.5 — auth middleware.

Exit criteria: every non-/health route rejects requests without a valid
Supabase JWT.

Signature/expiry checks run against a locally-generated EC keypair injected
via app.core.auth.set_jwks_client, so this suite is deterministic and needs
no network call to Supabase — it tests the verification logic itself, not
Supabase's uptime. A separate live check (this session, against the real
project's JWKS endpoint and a real signed-in user) is run manually and
reported alongside this suite's output, since that's the only way to prove
interop with Supabase's actual token format.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

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
def _wire_jwks(keypair, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    yield
    auth_module.set_jwks_client(None)


def make_token(private_key, *, exp_delta=3600, **overrides):
    payload = {
        "iss": TEST_ISSUER,
        "sub": TEST_SUB,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + exp_delta,
        **overrides,
    }
    return jwt.encode(payload, private_key, algorithm="ES256")


@pytest.fixture
def client():
    return TestClient(app)


def test_health_requires_no_auth(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_protected_route_with_no_token_returns_401(client):
    response = client.get("/api/v1/_probe")
    assert response.status_code == 401


def test_protected_route_with_tampered_token_returns_401(client, keypair):
    private_key, _public_key = keypair
    token = make_token(private_key)
    tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]
    response = client.get(
        "/api/v1/_probe", headers={"Authorization": f"Bearer {tampered}"}
    )
    assert response.status_code == 401


def test_protected_route_with_expired_token_returns_401(client, keypair):
    private_key, _public_key = keypair
    token = make_token(private_key, exp_delta=-10)
    response = client.get(
        "/api/v1/_probe", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_protected_route_with_valid_token_reaches_handler(client, keypair):
    private_key, _public_key = keypair
    token = make_token(private_key)
    response = client.get(
        "/api/v1/_probe", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == TEST_SUB


def test_protected_route_with_wrong_issuer_returns_401(client, keypair):
    private_key, _public_key = keypair
    token = make_token(private_key, iss="https://attacker.supabase.co/auth/v1")
    response = client.get(
        "/api/v1/_probe", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
