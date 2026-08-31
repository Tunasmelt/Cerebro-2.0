"""Stage 0.6 — rate limiting.

Exit criteria: limits from architecture-and-security.md's rate-limit table
are enforced per user, per route class.

Real chat/upload/seal/graph endpoints don't exist yet (Phase 1/3), so these
tests hit the documented future paths directly (e.g. POST /api/v1/documents)
— RateLimitMiddleware runs before routing, so a request within budget still
reaches routing (404, since no handler exists yet) while a request over
budget never gets that far (429). That 404-vs-429 distinction is exactly
how we prove the limiter is doing the gating, not the router.

Uses the same JWKS test seam as Stage 0.5 so this is deterministic and
network-free, plus an injectable clock so the "resets after the window
elapses" test doesn't need to sleep 60 real seconds.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core import documents_storage as documents_storage_module
from app.core import rate_limit as rate_limit_module
from app.core.documents_storage import SignedUpload
from app.core.rate_limit import RateLimiter
from app.main import app

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"


class _StubJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._key)


def make_token(private_key, sub, *, exp_delta=3600):
    payload = {
        "iss": TEST_ISSUER,
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + exp_delta,
    }
    return jwt.encode(payload, private_key, algorithm="ES256")


@pytest.fixture
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture
def fake_clock():
    state = {"now": 1000.0}

    def clock():
        return state["now"]

    clock.state = state
    return clock


class _FakeDocumentsStorage:
    """Just enough to let upload-init's real handler succeed without any
    network — this test is about the rate limiter, not upload logic
    (already covered by test_stage_1_1_upload.py)."""

    async def authorize(self, *, user_jwt, user_id, title, mime):
        return SignedUpload(document_id="doc-x", upload_url="https://fake/doc-x")

    async def confirm(self, *, user_jwt, user_id, document_id):
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _wire_test_seams(keypair, fake_clock, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    rate_limit_module.set_rate_limiter(RateLimiter(clock=fake_clock))
    documents_storage_module.set_documents_storage(_FakeDocumentsStorage())
    yield
    auth_module.set_jwks_client(None)
    rate_limit_module.set_rate_limiter(RateLimiter())
    documents_storage_module.set_documents_storage(
        documents_storage_module.SupabaseDocumentsStorage()
    )


@pytest.fixture
def client():
    return TestClient(app)


def auth_headers(private_key, sub="11111111-1111-1111-1111-111111111111"):
    return {"Authorization": f"Bearer {make_token(private_key, sub)}"}


def test_chat_burst_returns_429_on_the_21st_request(client, keypair):
    private_key, _ = keypair
    headers = auth_headers(private_key)

    for i in range(20):
        response = client.post(
            "/api/v1/chat/sessions/x/stream", headers=headers
        )
        assert response.status_code != 429, f"request {i + 1} was rate limited early"

    response = client.post("/api/v1/chat/sessions/x/stream", headers=headers)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in response.headers


def test_limit_resets_after_the_window_elapses(client, keypair, fake_clock):
    private_key, _ = keypair
    headers = auth_headers(private_key)

    for _ in range(20):
        client.post("/api/v1/chat/sessions/x/stream", headers=headers)
    blocked = client.post("/api/v1/chat/sessions/x/stream", headers=headers)
    assert blocked.status_code == 429

    fake_clock.state["now"] += 61  # chat window is 60s

    recovered = client.post("/api/v1/chat/sessions/x/stream", headers=headers)
    assert recovered.status_code != 429


def test_limit_is_scoped_per_user(client, keypair):
    private_key, _ = keypair
    user_a = auth_headers(private_key, sub="11111111-1111-1111-1111-111111111111")
    user_b = auth_headers(private_key, sub="22222222-2222-2222-2222-222222222222")

    for _ in range(20):
        client.post("/api/v1/chat/sessions/x/stream", headers=user_a)
    a_blocked = client.post("/api/v1/chat/sessions/x/stream", headers=user_a)
    assert a_blocked.status_code == 429

    b_first = client.post("/api/v1/chat/sessions/x/stream", headers=user_b)
    assert b_first.status_code != 429


def test_limit_is_scoped_per_route_class(client, keypair):
    private_key, _ = keypair
    headers = auth_headers(private_key)

    for _ in range(20):
        client.post("/api/v1/chat/sessions/x/stream", headers=headers)
    chat_blocked = client.post("/api/v1/chat/sessions/x/stream", headers=headers)
    assert chat_blocked.status_code == 429

    graph_request = client.get("/api/v1/graph/nodes", headers=headers)
    assert graph_request.status_code != 429


def test_upload_class_uses_the_10_per_hour_limit(client, keypair):
    # Regression test: this used to hit the stale placeholder path
    # POST /api/v1/documents — a path documents.py never actually
    # implements (the real route is /api/v1/documents/upload-init) —
    # so it passed by testing the wrong thing while the real route
    # silently fell through to the "general" 100/min class instead.
    # Caught live via a Phase 0 audit that actually burst-tested
    # production: 15 real upload-init calls succeeded where a 429
    # should have landed at the 11th. Fixed in rate_limit.py's
    # classify_route; this test now hits the real route.
    private_key, _ = keypair
    headers = auth_headers(private_key)
    body = {"filename": "x.txt", "mime": "text/plain", "size_bytes": 10}

    for i in range(10):
        response = client.post(
            "/api/v1/documents/upload-init", headers=headers, json=body
        )
        assert response.status_code != 429, f"upload {i + 1} was rate limited early"

    response = client.post(
        "/api/v1/documents/upload-init", headers=headers, json=body
    )
    assert response.status_code == 429


def test_seal_unseal_class_uses_the_5_per_hour_limit(client, keypair):
    private_key, _ = keypair
    headers = auth_headers(private_key)

    for i in range(5):
        response = client.post(
            "/api/v1/documents/doc-123/seal", headers=headers
        )
        assert response.status_code != 429, f"attempt {i + 1} was rate limited early"

    response = client.post("/api/v1/documents/doc-123/seal", headers=headers)
    assert response.status_code == 429


def test_general_api_class_uses_the_100_per_minute_limit(client, keypair):
    private_key, _ = keypair
    headers = auth_headers(private_key)

    for i in range(100):
        response = client.get("/api/v1/documents/doc-123", headers=headers)
        assert response.status_code != 429, f"request {i + 1} was rate limited early"

    response = client.get("/api/v1/documents/doc-123", headers=headers)
    assert response.status_code == 429


def test_health_is_never_rate_limited(client):
    for _ in range(150):
        response = client.get("/health")
        assert response.status_code == 200
