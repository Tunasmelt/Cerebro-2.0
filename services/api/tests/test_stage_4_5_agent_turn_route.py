"""Route-level tests for Stage 4.5's POST /chat/sessions/{id}/agent-turn,
mirroring test_chat_routes.py's TestClient + fake-storage pattern. The
tool-calling logic itself is covered by test_stage_4_5_agent_tools.py;
this proves the FastAPI wiring — auth, session ownership (404-not-403),
and that the route surfaces run_agent_turn's result correctly.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.chat import storage as chat_storage_module
from app.chat.agent_tools import AgentTurnResult
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


class _FakeChatStorage:
    def __init__(self):
        self.sessions: dict[str, str] = {}

    async def create_session(self, *, user_jwt, user_id):
        session_id = f"session-{len(self.sessions) + 1}"
        self.sessions[session_id] = user_jwt
        return session_id

    async def get_session(self, *, user_jwt, session_id):
        owner_jwt = self.sessions.get(session_id)
        if owner_jwt is None or owner_jwt != user_jwt:
            return None
        return {"id": session_id}


@pytest.fixture
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture
def chat_storage():
    return _FakeChatStorage()


@pytest.fixture(autouse=True)
def _wire_test_seams(keypair, chat_storage, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    chat_storage_module.set_chat_storage(chat_storage)
    yield
    auth_module.set_jwks_client(None)
    chat_storage_module.set_chat_storage(chat_storage_module.SupabaseChatStorage())


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


def test_agent_turn_happy_path(client, keypair, chat_storage, monkeypatch):
    private_key, _ = keypair
    headers = auth_headers(private_key)

    created = client.post("/api/v1/chat/sessions", headers=headers)
    session_id = created.json()["id"]

    async def fake_run_agent_turn(*, user_jwt, user_id, message):
        assert message == "add a card to buy milk"
        return AgentTurnResult(
            response='Created "Buy milk".', created_cards=[{"id": "c1", "title": "Buy milk"}]
        )

    import app.routes.chat as chat_routes_module

    monkeypatch.setattr(chat_routes_module, "run_agent_turn", fake_run_agent_turn)

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/agent-turn",
        headers=headers,
        json={"message": "add a card to buy milk"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["response"] == 'Created "Buy milk".'
    assert body["created_cards"] == [{"id": "c1", "title": "Buy milk"}]


def test_agent_turn_on_another_users_session_returns_404_not_403(client, keypair, chat_storage):
    private_key, _ = keypair
    owner_headers = auth_headers(private_key, sub=TEST_SUB)
    other_headers = auth_headers(private_key, sub=OTHER_SUB)

    created = client.post("/api/v1/chat/sessions", headers=owner_headers)
    session_id = created.json()["id"]

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/agent-turn",
        headers=other_headers,
        json={"message": "add a card"},
    )
    assert response.status_code == 404


def test_agent_turn_on_nonexistent_session_returns_404(client, keypair):
    private_key, _ = keypair
    response = client.post(
        "/api/v1/chat/sessions/does-not-exist/agent-turn",
        headers=auth_headers(private_key),
        json={"message": "add a card"},
    )
    assert response.status_code == 404


def test_agent_turn_requires_auth(client):
    response = client.post(
        "/api/v1/chat/sessions/session-1/agent-turn", json={"message": "add a card"}
    )
    assert response.status_code == 401
