"""Stage 5.4 — persistent-edge graph rendering. Exercises the pure
aggregate_to_document_edges function directly (fixture chunk_edges +
chunk-to-document maps, no I/O), plus SupabaseChunkEdgesStorage's new
list_all_edges/resolve_chunk_documents methods against a fake httpx
transport, plus get_associative_document_edges' orchestration.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.graph import edges as edges_module
from app.graph.edges import (
    DECAY_HALF_LIFE_HOURS,
    EXPLICIT_LINK_WEIGHT,
    ChunkEdge,
    SupabaseChunkEdgesStorage,
    aggregate_to_document_edges,
    get_associative_document_edges,
)


def _edge(source, target, *, weight=1.0, is_explicit=False, hours_ago=0.0):
    return ChunkEdge(
        id=f"{source}-{target}",
        source_chunk_id=source,
        target_chunk_id=target,
        weight=weight,
        co_retrieval_count=1,
        is_explicit=is_explicit,
        last_reinforced_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )


# --- aggregate_to_document_edges (pure) --------------------------------------


def test_aggregate_drops_pairs_within_the_same_document():
    edges = [_edge("c1", "c2")]
    chunk_to_document = {"c1": "doc-a", "c2": "doc-a"}  # same document

    result = aggregate_to_document_edges(edges, chunk_to_document)

    assert result == []


def test_aggregate_sums_multiple_chunk_pairs_into_one_document_edge():
    edges = [_edge("c1", "c2", weight=2.0), _edge("c3", "c4", weight=3.0)]
    chunk_to_document = {"c1": "doc-a", "c2": "doc-b", "c3": "doc-a", "c4": "doc-b"}

    result = aggregate_to_document_edges(edges, chunk_to_document)

    assert len(result) == 1
    assert {result[0].document_id, result[0].neighbor_document_id} == {"doc-a", "doc-b"}
    assert result[0].weight == pytest.approx(5.0)


def test_aggregate_is_undirected_regardless_of_document_order():
    edges_ab = aggregate_to_document_edges(
        [_edge("c1", "c2")], {"c1": "doc-a", "c2": "doc-b"}
    )
    edges_ba = aggregate_to_document_edges(
        [_edge("c1", "c2")], {"c1": "doc-b", "c2": "doc-a"}
    )
    assert (edges_ab[0].document_id, edges_ab[0].neighbor_document_id) == (
        edges_ba[0].document_id,
        edges_ba[0].neighbor_document_id,
    )


def test_aggregate_applies_decay_to_non_explicit_edges():
    now = datetime.now(timezone.utc)
    edges = [_edge("c1", "c2", weight=10.0, hours_ago=DECAY_HALF_LIFE_HOURS)]
    chunk_to_document = {"c1": "doc-a", "c2": "doc-b"}

    result = aggregate_to_document_edges(edges, chunk_to_document, now=now)

    assert result[0].weight == pytest.approx(5.0)


def test_aggregate_marks_explicit_if_any_contributing_edge_is_explicit():
    edges = [
        _edge("c1", "c2", weight=1.0, is_explicit=False),
        _edge("c3", "c4", weight=EXPLICIT_LINK_WEIGHT, is_explicit=True),
    ]
    chunk_to_document = {"c1": "doc-a", "c2": "doc-b", "c3": "doc-a", "c4": "doc-b"}

    result = aggregate_to_document_edges(edges, chunk_to_document)

    assert result[0].is_explicit is True


def test_aggregate_skips_edges_with_an_unresolved_chunk():
    # A chunk id with no entry in chunk_to_document (e.g. a race with a
    # deleted document) shouldn't raise — just isn't renderable.
    edges = [_edge("c1", "c2")]
    result = aggregate_to_document_edges(edges, {"c1": "doc-a"})
    assert result == []


# --- SupabaseChunkEdgesStorage: list_all_edges / resolve_chunk_documents ----


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, edges, chunks):
        self._edges = edges
        self._chunks = chunks

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        if path == "/rest/v1/chunk_edges" and request.method == "GET":
            return httpx.Response(200, json=self._edges)
        if path == "/rest/v1/chunks" and request.method == "GET":
            requested = params["id"].removeprefix("in.(").rstrip(")").split(",")
            rows = [c for c in self._chunks if c["id"] in requested]
            return httpx.Response(200, json=rows)
        raise AssertionError(f"unexpected {request.method} {path}")


def _patch_client(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


@pytest.mark.asyncio
async def test_list_all_edges_returns_every_row(monkeypatch):
    transport = _FakeTransport(
        edges=[
            {
                "id": "e1",
                "source_chunk_id": "c1",
                "target_chunk_id": "c2",
                "weight": 1.0,
                "co_retrieval_count": 1,
                "is_explicit": False,
                "last_reinforced_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        chunks=[],
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseChunkEdgesStorage()

    edges = await storage.list_all_edges(user_jwt="t")

    assert len(edges) == 1
    assert edges[0].source_chunk_id == "c1"


@pytest.mark.asyncio
async def test_resolve_chunk_documents_maps_ids(monkeypatch):
    transport = _FakeTransport(
        edges=[],
        chunks=[{"id": "c1", "document_id": "doc-a"}, {"id": "c2", "document_id": "doc-b"}],
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseChunkEdgesStorage()

    resolved = await storage.resolve_chunk_documents(user_jwt="t", chunk_ids=["c1", "c2"])

    assert resolved == {"c1": "doc-a", "c2": "doc-b"}


@pytest.mark.asyncio
async def test_resolve_chunk_documents_with_no_ids_makes_no_request(monkeypatch):
    transport = _FakeTransport(edges=[], chunks=[])
    _patch_client(monkeypatch, transport)
    storage = SupabaseChunkEdgesStorage()

    resolved = await storage.resolve_chunk_documents(user_jwt="t", chunk_ids=[])

    assert resolved == {}


@pytest.mark.asyncio
async def test_get_associative_document_edges_end_to_end(monkeypatch):
    transport = _FakeTransport(
        edges=[
            {
                "id": "e1",
                "source_chunk_id": "c1",
                "target_chunk_id": "c2",
                "weight": 2.0,
                "co_retrieval_count": 2,
                "is_explicit": False,
                "last_reinforced_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        chunks=[{"id": "c1", "document_id": "doc-a"}, {"id": "c2", "document_id": "doc-b"}],
    )
    _patch_client(monkeypatch, transport)
    edges_module.set_chunk_edges_storage(SupabaseChunkEdgesStorage())

    result = await get_associative_document_edges(user_jwt="t")

    assert len(result) == 1
    assert {result[0]["document_id"], result[0]["neighbor_document_id"]} == {"doc-a", "doc-b"}
    assert result[0]["weight"] == pytest.approx(2.0)
    edges_module.set_chunk_edges_storage(SupabaseChunkEdgesStorage())


@pytest.mark.asyncio
async def test_get_associative_document_edges_filters_a_single_reinforcement(monkeypatch):
    # A single shared retrieval (weight=1.0, REINFORCEMENT_INCREMENT) is
    # exactly the "asked one question, five chunks came back, every pair
    # among them got an edge" case reported live as "all nodes connected"
    # after one question on a small vault — it must not render.
    transport = _FakeTransport(
        edges=[
            {
                "id": "e1",
                "source_chunk_id": "c1",
                "target_chunk_id": "c2",
                "weight": 1.0,
                "co_retrieval_count": 1,
                "is_explicit": False,
                "last_reinforced_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        chunks=[{"id": "c1", "document_id": "doc-a"}, {"id": "c2", "document_id": "doc-b"}],
    )
    _patch_client(monkeypatch, transport)
    edges_module.set_chunk_edges_storage(SupabaseChunkEdgesStorage())

    result = await get_associative_document_edges(user_jwt="t")

    assert result == []
    edges_module.set_chunk_edges_storage(SupabaseChunkEdgesStorage())


@pytest.mark.asyncio
async def test_get_associative_document_edges_with_no_edges_returns_empty(monkeypatch):
    transport = _FakeTransport(edges=[], chunks=[])
    _patch_client(monkeypatch, transport)
    edges_module.set_chunk_edges_storage(SupabaseChunkEdgesStorage())

    result = await get_associative_document_edges(user_jwt="t")

    assert result == []
    edges_module.set_chunk_edges_storage(SupabaseChunkEdgesStorage())
