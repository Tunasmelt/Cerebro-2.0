"""Stage 2.5 — storage-level tests for the four new SupabaseGraphStorage
methods against a fake httpx transport, same pattern as
test_stage_2_4_replay.py."""
import httpx
import pytest

from app.graph.storage import SupabaseGraphStorage


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.clusters = [
            {"id": "cluster-1", "centroid_embedding": "[0.1,0.2,0.3]"},
        ]
        self.incremental_document_clusters = [{"document_id": "doc-a"}]
        self.chunks = [{"embedding": "[0.4,0.5,0.6]"}]
        self.insert_calls: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/v1/clusters" and request.method == "GET":
            return httpx.Response(200, json=self.clusters)
        if path == "/rest/v1/document_clusters" and request.method == "GET":
            return httpx.Response(200, json=self.incremental_document_clusters)
        if path == "/rest/v1/chunks" and request.method == "GET":
            return httpx.Response(200, json=self.chunks)
        if path == "/rest/v1/document_clusters" and request.method == "POST":
            import json as _json

            self.insert_calls.append(_json.loads(request.content))
            return httpx.Response(201, json=[{"id": "dc-1"}])
        raise AssertionError(f"unexpected {request.method} {path}")


@pytest.fixture(autouse=True)
def _patch_httpx_client(monkeypatch):
    transport = _FakeTransport()
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    return transport


@pytest.mark.asyncio
async def test_get_clusters_with_centroids_parses_halfvec_strings(_patch_httpx_client):
    storage = SupabaseGraphStorage()
    clusters = await storage.get_clusters_with_centroids(user_jwt="t")
    assert clusters == [{"id": "cluster-1", "centroid_embedding": [0.1, 0.2, 0.3]}]


@pytest.mark.asyncio
async def test_count_incremental_placements_counts_rows(_patch_httpx_client):
    storage = SupabaseGraphStorage()
    count = await storage.count_incremental_placements(user_jwt="t")
    assert count == 1


@pytest.mark.asyncio
async def test_get_document_chunk_embeddings_parses_halfvec_strings(_patch_httpx_client):
    storage = SupabaseGraphStorage()
    embeddings = await storage.get_document_chunk_embeddings(
        user_jwt="t", document_id="doc-a"
    )
    assert embeddings == [[0.4, 0.5, 0.6]]


@pytest.mark.asyncio
async def test_insert_incremental_assignment_posts_placement_method(_patch_httpx_client):
    storage = SupabaseGraphStorage()
    await storage.insert_incremental_assignment(
        user_jwt="t", user_id="u1", document_id="doc-new", cluster_id="cluster-1", distance=1.5
    )
    assert _patch_httpx_client.insert_calls == [
        {
            "document_id": "doc-new",
            "cluster_id": "cluster-1",
            "user_id": "u1",
            "distance": 1.5,
            "placement_method": "incremental",
        }
    ]
