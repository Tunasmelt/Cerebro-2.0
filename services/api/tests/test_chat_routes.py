"""Route-level tests for Stage 1.7's chat endpoints (routes/chat.py),
mirroring test_stage_1_1_upload.py's TestClient pattern — the
orchestration/SSE-contract logic itself is covered in
test_stage_1_7_chat.py; this file proves the actual FastAPI wiring:
auth enforcement, 404-not-403 on another user's session, and that the
streaming endpoint really streams SSE bytes.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.chat import generate as generate_module
from app.chat import storage as chat_storage_module
from app.chat.generate import set_generate_client
from app.core import auth as auth_module
from app.ingest import embed as embed_module
from app.main import app
from app.retrieve import retrieve as retrieve_module

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
        self.sessions: dict[str, str] = {}  # session_id -> owner's raw JWT
        self.messages: dict[str, list[dict]] = {}

    async def create_session(self, *, user_jwt, user_id):
        session_id = f"session-{len(self.sessions) + 1}"
        self.sessions[session_id] = user_jwt
        self.messages[session_id] = []
        return session_id

    async def get_session(self, *, user_jwt, session_id):
        # Real RLS scopes this query to rows the caller's JWT actually
        # owns — simulated here by only "finding" a session if the
        # requesting JWT matches the one it was created with.
        owner_jwt = self.sessions.get(session_id)
        if owner_jwt is None or owner_jwt != user_jwt:
            return None
        return {"id": session_id}

    async def save_message(self, **kwargs):
        pass

    async def list_sessions(self, *, user_jwt):
        return [
            {"id": sid, "created_at": "2026-01-01T00:00:00Z"}
            for sid, owner in self.sessions.items()
            if owner == user_jwt
        ]

    async def get_messages(self, *, user_jwt, session_id):
        owner_jwt = self.sessions.get(session_id)
        if owner_jwt is None or owner_jwt != user_jwt:
            return None
        return self.messages.get(session_id, [])

    async def delete_session(self, *, user_jwt, session_id):
        owner_jwt = self.sessions.get(session_id)
        if owner_jwt is None or owner_jwt != user_jwt:
            return False
        del self.sessions[session_id]
        self.messages.pop(session_id, None)
        return True


class _FakeEmbedClient:
    provider = "jina"

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        return [0.1] * 1024

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
        raise NotImplementedError


class _FakeRerankClient:
    async def rerank(self, *, query, documents, top_n):
        return []


class _FakeRetrieveStorage:
    async def vector_search(self, *, user_jwt, query_embedding, match_count, primary_provider):
        return []

    async def fts_search(self, *, user_jwt, query_text, match_count):
        return []


class _FakeGenerateClient:
    async def stream_text(self, *, system_instruction, input_text):
        yield "hi"


@pytest.fixture
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture
def chat_storage():
    return _FakeChatStorage()


async def _no_op_run_interaction(**kwargs):
    # retrieve() now runs HyDE unconditionally (chat/stream.py passes
    # use_hyde=True) — without this stub, every route test that reaches
    # stream_chat would fire a real network call to Gemini via
    # retrieve/hyde.py's run_interaction.
    return {"steps": []}


@pytest.fixture(autouse=True)
def _wire_test_seams(keypair, chat_storage, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    chat_storage_module.set_chat_storage(chat_storage)
    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(_FakeRerankClient())
    retrieve_module.set_retrieve_storage(_FakeRetrieveStorage())
    set_generate_client(_FakeGenerateClient())
    monkeypatch.setattr(generate_module, "run_interaction", _no_op_run_interaction)
    yield
    auth_module.set_jwks_client(None)
    chat_storage_module.set_chat_storage(chat_storage_module.SupabaseChatStorage())
    embed_module.set_embed_client(embed_module.JinaEmbedClient())
    retrieve_module.set_rerank_client(retrieve_module.CohereRerankClient())
    retrieve_module.set_retrieve_storage(retrieve_module.SupabaseRetrieveStorage())
    from app.chat.generate import GeminiGenerateClient
    set_generate_client(GeminiGenerateClient())


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


def test_create_session_and_stream_happy_path(client, keypair, chat_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)

    created = client.post("/api/v1/chat/sessions", headers=headers)
    assert created.status_code == 201
    session_id = created.json()["id"]

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/stream",
        headers=headers,
        json={"query": "hello"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: retrieval" in response.text
    assert "event: done" in response.text


def test_stream_on_another_users_session_returns_404_not_403(client, keypair, chat_storage):
    private_key, _ = keypair
    owner_headers = auth_headers(private_key, sub=TEST_SUB)
    other_headers = auth_headers(private_key, sub=OTHER_SUB)

    created = client.post("/api/v1/chat/sessions", headers=owner_headers)
    session_id = created.json()["id"]

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/stream",
        headers=other_headers,
        json={"query": "hello"},
    )
    assert response.status_code == 404


def test_stream_on_nonexistent_session_returns_404(client, keypair):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    response = client.post(
        "/api/v1/chat/sessions/does-not-exist/stream",
        headers=headers,
        json={"query": "hello"},
    )
    assert response.status_code == 404


def test_chat_endpoints_require_auth(client):
    assert client.post("/api/v1/chat/sessions").status_code == 401
    assert (
        client.post(
            "/api/v1/chat/sessions/session-1/stream", json={"query": "hi"}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/chat/sessions").status_code == 401
    assert client.get("/api/v1/chat/sessions/session-1/messages").status_code == 401


# --- Stage 2.4: session history for reopening a past conversation --------------


def test_list_sessions_returns_only_the_callers_own(client, keypair, chat_storage):
    private_key, _ = keypair
    owner_headers = auth_headers(private_key, sub=TEST_SUB)
    other_headers = auth_headers(private_key, sub=OTHER_SUB)

    client.post("/api/v1/chat/sessions", headers=owner_headers)
    client.post("/api/v1/chat/sessions", headers=other_headers)

    response = client.get("/api/v1/chat/sessions", headers=owner_headers)
    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert len(sessions) == 1


def test_get_messages_for_nonexistent_session_returns_404(client, keypair):
    private_key, _ = keypair
    response = client.get(
        "/api/v1/chat/sessions/does-not-exist/messages", headers=auth_headers(private_key)
    )
    assert response.status_code == 404


# --- Chat management pass: DELETE /chat/sessions/{id} ---------------------------


def test_delete_session_happy_path(client, keypair, chat_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    session_id = client.post("/api/v1/chat/sessions", headers=headers).json()["id"]

    response = client.delete(f"/api/v1/chat/sessions/{session_id}", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"id": session_id, "deleted": True}
    # Really gone, not just reported as deleted.
    assert client.get("/api/v1/chat/sessions", headers=headers).json()["sessions"] == []


def test_delete_session_on_another_users_session_returns_404_not_403(client, keypair, chat_storage):
    private_key, _ = keypair
    owner_headers = auth_headers(private_key, sub=TEST_SUB)
    other_headers = auth_headers(private_key, sub=OTHER_SUB)
    session_id = client.post("/api/v1/chat/sessions", headers=owner_headers).json()["id"]

    response = client.delete(f"/api/v1/chat/sessions/{session_id}", headers=other_headers)

    assert response.status_code == 404
    # Untouched — the other user's delete attempt did nothing.
    assert len(client.get("/api/v1/chat/sessions", headers=owner_headers).json()["sessions"]) == 1


def test_delete_session_for_nonexistent_session_returns_404(client, keypair):
    private_key, _ = keypair
    response = client.delete(
        "/api/v1/chat/sessions/does-not-exist", headers=auth_headers(private_key)
    )
    assert response.status_code == 404


def test_delete_session_requires_auth(client):
    assert client.delete("/api/v1/chat/sessions/session-1").status_code == 401


def test_get_messages_on_another_users_session_returns_404_not_403(
    client, keypair, chat_storage
):
    private_key, _ = keypair
    owner_headers = auth_headers(private_key, sub=TEST_SUB)
    other_headers = auth_headers(private_key, sub=OTHER_SUB)

    created = client.post("/api/v1/chat/sessions", headers=owner_headers)
    session_id = created.json()["id"]

    response = client.get(
        f"/api/v1/chat/sessions/{session_id}/messages", headers=other_headers
    )
    assert response.status_code == 404


def test_get_messages_returns_the_fake_storage_shape(client, keypair, chat_storage):
    private_key, _ = keypair
    headers = auth_headers(private_key)
    created = client.post("/api/v1/chat/sessions", headers=headers)
    session_id = created.json()["id"]
    chat_storage.messages[session_id] = [
        {
            "id": "m1",
            "role": "assistant",
            "content": "answer",
            "retrieved_chunk_ids": ["c1"],
            "retrieved_document_ids": ["d1"],
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]

    response = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
    assert response.status_code == 200
    assert response.json()["messages"][0]["retrieved_document_ids"] == ["d1"]
