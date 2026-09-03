"""Document/graph quality-of-life pass — storage-level tests against a
fake httpx transport, same pattern as test_stage_2_5_storage.py /
test_stage_3_6_document_storage.py.

Covers two real gaps: get_nodes used to filter status=eq.ready only, so
sealing a document made its node vanish from the graph entirely instead
of just hiding its content (see graph/storage.py's get_nodes docstring);
and there was no way to rename a document at all.
"""
import httpx
import pytest

from app.core.documents_storage import SupabaseDocumentsStorage
from app.graph.storage import SupabaseGraphStorage


class _NodesTransport(httpx.AsyncBaseTransport):
    def __init__(self, documents: list[dict]):
        self.documents = documents
        self.last_params: dict | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/v1/documents" and request.method == "GET":
            self.last_params = dict(request.url.params)
            return httpx.Response(200, json=self.documents)
        raise AssertionError(f"unexpected {request.method} {request.url.path}")


class _RenameTransport(httpx.AsyncBaseTransport):
    def __init__(self, matched_rows: list[dict]):
        self.matched_rows = matched_rows
        self.last_json: dict | None = None
        self.last_params: dict | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/v1/documents" and request.method == "PATCH":
            import json as _json

            self.last_json = _json.loads(request.content)
            self.last_params = dict(request.url.params)
            return httpx.Response(200, json=self.matched_rows)
        raise AssertionError(f"unexpected {request.method} {request.url.path}")


def _patch_client(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


@pytest.mark.asyncio
async def test_get_nodes_requests_ready_and_sealed_statuses(monkeypatch):
    transport = _NodesTransport(documents=[])
    _patch_client(monkeypatch, transport)
    storage = SupabaseGraphStorage()

    await storage.get_nodes(user_jwt="t")

    assert transport.last_params["status"] == "in.(ready,sealed)"
    assert "mime" in transport.last_params["select"]
    assert "status" in transport.last_params["select"]


@pytest.mark.asyncio
async def test_get_nodes_returns_mime_and_status_per_node(monkeypatch):
    transport = _NodesTransport(
        documents=[
            {
                "id": "doc-1",
                "title": "cat.png",
                "mime": "image/png",
                "status": "ready",
                "document_clusters": None,
            },
            {
                "id": "doc-2",
                "title": "secret.pdf",
                "mime": "application/pdf",
                "status": "sealed",
                "document_clusters": {
                    "cluster_id": "c1",
                    "clusters": {"centroid_x": 1.0, "centroid_y": 2.0, "centroid_z": 3.0},
                },
            },
        ]
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseGraphStorage()

    nodes = await storage.get_nodes(user_jwt="t")

    assert nodes[0]["mime"] == "image/png"
    assert nodes[0]["status"] == "ready"
    assert nodes[1]["mime"] == "application/pdf"
    assert nodes[1]["status"] == "sealed"
    assert nodes[1]["cluster_id"] == "c1"


@pytest.mark.asyncio
async def test_rename_document_sends_patch_with_new_title(monkeypatch):
    transport = _RenameTransport(matched_rows=[{"id": "doc-1", "title": "New title"}])
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    renamed = await storage.rename_document(
        user_jwt="t", document_id="doc-1", title="New title"
    )

    assert renamed is True
    assert transport.last_json == {"title": "New title"}
    assert transport.last_params["id"] == "eq.doc-1"


@pytest.mark.asyncio
async def test_rename_document_returns_false_for_unmatched_document(monkeypatch):
    # RLS makes another user's (or a nonexistent) document invisible —
    # the PATCH matches zero rows rather than erroring, same 404-not-403
    # pattern delete_document/delete_session already use.
    transport = _RenameTransport(matched_rows=[])
    _patch_client(monkeypatch, transport)
    storage = SupabaseDocumentsStorage()

    renamed = await storage.rename_document(
        user_jwt="t", document_id="not-mine", title="New title"
    )

    assert renamed is False
