"""Route-level tests for Stage 4.4's read-only token/cost playground
endpoint (routes/chat.py's get_prompt_breakdown), mirroring
test_chat_routes.py's TestClient + fake-storage pattern.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.chat import playground as playground_module
from app.core import auth as auth_module
from app.main import app

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"
TEST_SUB = "11111111-1111-1111-1111-111111111111"
OTHER_SUB = "22222222-2222-2222-2222-222222222222"


class _StubJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._key)


class _FakePlaygroundStorage:
    def __init__(self):
        self.breakdown_by_key: dict[tuple[str, str], dict] = {}
        self.valid_session_ids: set[str] = set()
        self.run_result: dict | None = None
        self.last_run_call: dict | None = None

    async def get_prompt_breakdown(self, *, user_jwt, session_id, message_id):
        return self.breakdown_by_key.get((session_id, message_id))

    async def run_edited_prompt(
        self, *, user_jwt, session_id, system_instructions, context_sections, user_query
    ):
        self.last_run_call = {
            "session_id": session_id,
            "system_instructions": system_instructions,
            "context_sections": context_sections,
            "user_query": user_query,
        }
        if session_id not in self.valid_session_ids:
            return None
        return self.run_result


@pytest.fixture
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture
def playground_storage():
    return _FakePlaygroundStorage()


@pytest.fixture(autouse=True)
def _wire_test_seams(keypair, playground_storage, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    playground_module.set_chat_playground_storage(playground_storage)
    yield
    auth_module.set_jwks_client(None)
    playground_module.set_chat_playground_storage(playground_module.ChatPlaygroundStorage())


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


def test_get_prompt_breakdown_happy_path(client, keypair, playground_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    playground_storage.breakdown_by_key[("s1", "m1")] = {
        "model": "gemini-3.5-flash-lite",
        "sections": [{"label": "system_instructions", "content": "x", "tokens": 1, "citation": None}],
        "response": {"content": "answer", "tokens": 2},
        "total_tokens": 3,
        "estimated_cost_usd": 0.000001,
    }

    response = client.get("/api/v1/chat/sessions/s1/messages/m1/prompt", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_tokens"] == 3
    assert body["model"] == "gemini-3.5-flash-lite"


def test_get_prompt_breakdown_for_nonexistent_message_returns_404(client, keypair):
    private_key, _ = keypair
    response = client.get(
        "/api/v1/chat/sessions/s1/messages/does-not-exist/prompt",
        headers=auth_headers(private_key),
    )
    assert response.status_code == 404


def test_get_prompt_breakdown_requires_auth(client):
    assert client.get("/api/v1/chat/sessions/s1/messages/m1/prompt").status_code == 401


def test_run_playground_prompt_happy_path(client, keypair, playground_storage):
    private_key, _ = keypair
    playground_storage.valid_session_ids.add("s1")
    playground_storage.run_result = {
        "model": "gemini-3.5-flash-lite",
        "response": {"content": "the edited answer", "tokens": 4},
        "total_tokens": 20,
        "estimated_cost_usd": 0.00001,
        "latency_ms": 350,
    }

    response = client.post(
        "/api/v1/chat/sessions/s1/playground/run",
        headers=auth_headers(private_key),
        json={
            "system_instructions": "edited system text",
            "context_sections": [{"chunk_id": "c1", "content": "edited chunk"}],
            "user_query": "edited query",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["response"]["content"] == "the edited answer"
    assert body["latency_ms"] == 350
    assert playground_storage.last_run_call == {
        "session_id": "s1",
        "system_instructions": "edited system text",
        "context_sections": [{"chunk_id": "c1", "content": "edited chunk"}],
        "user_query": "edited query",
    }


def test_run_playground_prompt_for_nonexistent_session_returns_404(client, keypair):
    private_key, _ = keypair
    response = client.post(
        "/api/v1/chat/sessions/does-not-exist/playground/run",
        headers=auth_headers(private_key),
        json={"system_instructions": "x", "context_sections": [], "user_query": "y"},
    )
    assert response.status_code == 404


def test_run_playground_prompt_requires_auth(client):
    response = client.post(
        "/api/v1/chat/sessions/s1/playground/run",
        json={"system_instructions": "x", "context_sections": [], "user_query": "y"},
    )
    assert response.status_code == 401


def test_run_playground_prompt_surfaces_generate_failure_as_502(
    client, keypair, playground_storage
):
    private_key, _ = keypair
    playground_storage.valid_session_ids.add("s1")
    playground_storage.run_result = {
        "error": {"code": "generate_call_failed", "message": "upstream boom"}
    }

    response = client.post(
        "/api/v1/chat/sessions/s1/playground/run",
        headers=auth_headers(private_key),
        json={"system_instructions": "x", "context_sections": [], "user_query": "y"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "generate_call_failed"
