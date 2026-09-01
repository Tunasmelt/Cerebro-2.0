"""Stage 2.2 — Graph API route-level tests, mirroring test_chat_routes.py's
TestClient pattern. The clustering algorithm itself is covered in
test_stage_2_1_clustering.py; this file proves the actual FastAPI
wiring — auth enforcement, 404 on an unknown/other-user's document, and
that responses have the documented shape.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.graph import cluster as cluster_module
from app.main import app

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"
TEST_SUB = "11111111-1111-1111-1111-111111111111"


class _StubJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._key)


class _FakeGraphStorage:
    def __init__(self):
        self.nodes = [{"id": "doc-1", "title": "x.txt", "cluster_id": "c1", "x": 0.1, "y": 0.2}]
        self.edges = [
            {"document_id": "doc-1", "neighbor_document_id": "doc-2", "distance": 0.5, "rank": 1}
        ]
        self.chunks_by_doc = {"doc-1": [{"id": "chunk-1", "ordinal": 0, "content": "hi", "meta": {}}]}

    async def get_ready_documents_with_chunk_embeddings(self, *, user_jwt):
        return []

    async def replace_graph(self, **kwargs):
        pass

    async def get_nodes(self, *, user_jwt):
        return self.nodes

    async def get_edges(self, *, user_jwt):
        return self.edges

    async def get_node_chunks(self, *, user_jwt, document_id):
        return self.chunks_by_doc.get(document_id)


@pytest.fixture
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture
def graph_storage():
    return _FakeGraphStorage()


@pytest.fixture(autouse=True)
def _wire_test_seams(keypair, graph_storage, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    cluster_module.set_graph_storage(graph_storage)
    yield
    auth_module.set_jwks_client(None)
    cluster_module.set_graph_storage(None)


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


def test_get_nodes_returns_the_fake_storage_shape(client, keypair):
    private_key, _ = keypair
    response = client.get("/api/v1/graph/nodes", headers=auth_headers(private_key))
    assert response.status_code == 200
    assert response.json() == {
        "nodes": [{"id": "doc-1", "title": "x.txt", "cluster_id": "c1", "x": 0.1, "y": 0.2}]
    }


def test_get_edges_returns_the_fake_storage_shape(client, keypair):
    private_key, _ = keypair
    response = client.get("/api/v1/graph/edges", headers=auth_headers(private_key))
    assert response.status_code == 200
    assert response.json()["edges"][0]["document_id"] == "doc-1"


def test_get_node_chunks_for_a_real_document(client, keypair):
    private_key, _ = keypair
    response = client.get(
        "/api/v1/graph/nodes/doc-1/chunks", headers=auth_headers(private_key)
    )
    assert response.status_code == 200
    assert response.json()["chunks"][0]["content"] == "hi"


def test_get_node_chunks_for_unknown_document_returns_404(client, keypair):
    private_key, _ = keypair
    response = client.get(
        "/api/v1/graph/nodes/does-not-exist/chunks", headers=auth_headers(private_key)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_recluster_returns_202(client, keypair):
    private_key, _ = keypair
    response = client.post("/api/v1/graph/recluster", headers=auth_headers(private_key))
    assert response.status_code == 202


def test_graph_endpoints_require_auth(client):
    assert client.get("/api/v1/graph/nodes").status_code == 401
    assert client.get("/api/v1/graph/edges").status_code == 401
    assert client.get("/api/v1/graph/nodes/doc-1/chunks").status_code == 401
    assert client.post("/api/v1/graph/recluster").status_code == 401
