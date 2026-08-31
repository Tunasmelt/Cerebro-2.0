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

    async def create_session(self, *, user_jwt, user_id):
        session_id = f"session-{len(self.sessions) + 1}"
        self.sessions[session_id] = user_jwt
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


class _FakeEmbedClient:
    provider = "jina"

    async def embed_text(self, text: str) -> list[float]:
        return [0.1] * 1024

    async def embed_image(self, image_bytes: bytes) -> list[float]:
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
