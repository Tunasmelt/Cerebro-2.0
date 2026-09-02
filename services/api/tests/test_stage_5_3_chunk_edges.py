"""Stage 5.3 — associative memory graph. Exercises pure decay/canonical-
pair logic directly, and SupabaseChunkEdgesStorage's real HTTP-wiring
logic against a fake httpx transport: reinforce_co_retrieval creates a
new pair, increments an existing one, and never touches an is_explicit
pair's weight; create_explicit_link enforces ownership of both chunks
and is undirected regardless of argument order; list_edges_for_chunks
returns edges touching any of the given chunks.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.graph.edges import (
    DECAY_HALF_LIFE_HOURS,
    EXPLICIT_LINK_WEIGHT,
    REINFORCEMENT_INCREMENT,
    ChunkEdge,
    SupabaseChunkEdgesStorage,
    _canonical_pair,
    decay_weight,
)


def test_canonical_pair_is_order_independent():
    assert _canonical_pair("b", "a") == _canonical_pair("a", "b") == ("a", "b")


def test_decay_weight_at_zero_elapsed_is_unchanged():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert decay_weight(weight=10.0, last_reinforced_at=now, now=now) == 10.0


def test_decay_weight_at_one_half_life_is_halved():
    reinforced_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = reinforced_at + timedelta(hours=DECAY_HALF_LIFE_HOURS)
    assert decay_weight(weight=10.0, last_reinforced_at=reinforced_at, now=now) == pytest.approx(5.0)


def test_decay_weight_never_negative_for_future_reinforced_at():
    reinforced_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)  # clock skew edge case
    assert decay_weight(weight=10.0, last_reinforced_at=reinforced_at, now=now) == 10.0


def test_explicit_edge_effective_weight_ignores_decay():
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    edge = ChunkEdge(
        id="e1",
        source_chunk_id="a",
        target_chunk_id="b",
        weight=EXPLICIT_LINK_WEIGHT,
        co_retrieval_count=0,
        is_explicit=True,
        last_reinforced_at=old,
    )
    assert edge.effective_weight(now=datetime(2026, 1, 1, tzinfo=timezone.utc)) == EXPLICIT_LINK_WEIGHT


def test_non_explicit_edge_effective_weight_decays():
    reinforced_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    edge = ChunkEdge(
        id="e1",
        source_chunk_id="a",
        target_chunk_id="b",
        weight=10.0,
        co_retrieval_count=3,
        is_explicit=False,
        last_reinforced_at=reinforced_at,
    )
    later = reinforced_at + timedelta(hours=DECAY_HALF_LIFE_HOURS)
    assert edge.effective_weight(now=later) == pytest.approx(5.0)


class _FakeChunkEdgesTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, existing_edges=None, chunks=None):
        self.edges: list[dict] = list(existing_edges or [])
        self.chunks = chunks or []
        self._next_id = 1
        self.requests: list[tuple[str, str, dict]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        method = request.method
        body = None
        if request.content:
            import json

            body = json.loads(request.content)
        self.requests.append((method, path, params))

        if path == "/rest/v1/chunks" and method == "GET":
            requested = params["id"].removeprefix("in.(").rstrip(")").split(",")
            rows = [c for c in self.chunks if c["id"] in requested]
            return httpx.Response(200, json=rows)

        if path == "/rest/v1/chunk_edges" and method == "GET":
            if "or" in params:
                requested = set(
                    params["or"]
                    .split("in.(")[1]
                    .split(")")[0]
                    .split(",")
                )
                rows = [
                    e
                    for e in self.edges
                    if e["source_chunk_id"] in requested or e["target_chunk_id"] in requested
                ]
                return httpx.Response(200, json=rows)
            source = params.get("source_chunk_id", "").removeprefix("eq.")
            target = params.get("target_chunk_id", "").removeprefix("eq.")
            rows = [
                e
                for e in self.edges
                if e["source_chunk_id"] == source and e["target_chunk_id"] == target
            ]
            return httpx.Response(200, json=rows)

        if path == "/rest/v1/chunk_edges" and method == "POST":
            existing_idx = None
            for i, e in enumerate(self.edges):
                if (
                    e["source_chunk_id"] == body["source_chunk_id"]
                    and e["target_chunk_id"] == body["target_chunk_id"]
                ):
                    existing_idx = i
            row = {"id": f"edge-{self._next_id}", **body}
            self._next_id += 1
            if existing_idx is not None:
                self.edges[existing_idx] = row
            else:
                self.edges.append(row)
            return httpx.Response(201, json=[row])

        if path == "/rest/v1/chunk_edges" and method == "PATCH":
            edge_id = params["id"].removeprefix("eq.")
            for e in self.edges:
                if e["id"] == edge_id:
                    e.update(body)
                    return httpx.Response(200, json=[e])
            return httpx.Response(200, json=[])

        raise AssertionError(f"unexpected {method} {path}")


def _patch_client(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


@pytest.mark.asyncio
async def test_reinforce_co_retrieval_creates_edges_for_every_pair(monkeypatch):
    transport = _FakeChunkEdgesTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseChunkEdgesStorage()

    await storage.reinforce_co_retrieval(
        user_jwt="t", user_id="u1", chunk_ids=["c1", "c2", "c3"]
    )

    assert len(transport.edges) == 3  # C(3,2)
    for e in transport.edges:
        assert e["weight"] == REINFORCEMENT_INCREMENT
        assert e["co_retrieval_count"] == 1
        assert e["is_explicit"] is False


@pytest.mark.asyncio
async def test_reinforce_co_retrieval_increments_an_existing_pair(monkeypatch):
    transport = _FakeChunkEdgesTransport(
        existing_edges=[
            {
                "id": "edge-1",
                "source_chunk_id": "c1",
                "target_chunk_id": "c2",
                "weight": 3.0,
                "co_retrieval_count": 3,
                "is_explicit": False,
                "last_reinforced_at": "2026-01-01T00:00:00+00:00",
            }
        ]
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseChunkEdgesStorage()

    await storage.reinforce_co_retrieval(user_jwt="t", user_id="u1", chunk_ids=["c2", "c1"])

    assert transport.edges[0]["weight"] == 3.0 + REINFORCEMENT_INCREMENT
    assert transport.edges[0]["co_retrieval_count"] == 4


@pytest.mark.asyncio
async def test_reinforce_co_retrieval_never_touches_an_explicit_pair(monkeypatch):
    transport = _FakeChunkEdgesTransport(
        existing_edges=[
            {
                "id": "edge-1",
                "source_chunk_id": "c1",
                "target_chunk_id": "c2",
                "weight": EXPLICIT_LINK_WEIGHT,
                "co_retrieval_count": 0,
                "is_explicit": True,
                "last_reinforced_at": "2026-01-01T00:00:00+00:00",
            }
        ]
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseChunkEdgesStorage()

    await storage.reinforce_co_retrieval(user_jwt="t", user_id="u1", chunk_ids=["c1", "c2"])

    assert transport.edges[0]["weight"] == EXPLICIT_LINK_WEIGHT
    assert transport.edges[0]["co_retrieval_count"] == 0


@pytest.mark.asyncio
async def test_reinforce_co_retrieval_with_fewer_than_two_chunks_is_a_noop(monkeypatch):
    transport = _FakeChunkEdgesTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseChunkEdgesStorage()

    await storage.reinforce_co_retrieval(user_jwt="t", user_id="u1", chunk_ids=["c1"])

    assert transport.edges == []
    assert transport.requests == []


@pytest.mark.asyncio
async def test_create_explicit_link_is_undirected_and_ownership_checked(monkeypatch):
    transport = _FakeChunkEdgesTransport(chunks=[{"id": "c1"}, {"id": "c2"}])
    _patch_client(monkeypatch, transport)
    storage = SupabaseChunkEdgesStorage()

    edge = await storage.create_explicit_link(
        user_jwt="t", user_id="u1", chunk_id_a="c2", chunk_id_b="c1"
    )

    assert edge is not None
    assert edge.is_explicit is True
    assert edge.weight == EXPLICIT_LINK_WEIGHT
    assert (edge.source_chunk_id, edge.target_chunk_id) == ("c1", "c2")


@pytest.mark.asyncio
async def test_create_explicit_link_fails_closed_for_unowned_or_missing_chunk(monkeypatch):
    transport = _FakeChunkEdgesTransport(chunks=[{"id": "c1"}])  # c2 not owned/found
    _patch_client(monkeypatch, transport)
    storage = SupabaseChunkEdgesStorage()

    edge = await storage.create_explicit_link(
        user_jwt="t", user_id="u1", chunk_id_a="c1", chunk_id_b="c2"
    )

    assert edge is None
    assert transport.edges == []


@pytest.mark.asyncio
async def test_list_edges_for_chunks_returns_edges_touching_any_given_chunk(monkeypatch):
    transport = _FakeChunkEdgesTransport(
        existing_edges=[
            {
                "id": "edge-1",
                "source_chunk_id": "c1",
                "target_chunk_id": "c2",
                "weight": 1.0,
                "co_retrieval_count": 1,
                "is_explicit": False,
                "last_reinforced_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "id": "edge-2",
                "source_chunk_id": "c9",
                "target_chunk_id": "c8",
                "weight": 1.0,
                "co_retrieval_count": 1,
                "is_explicit": False,
                "last_reinforced_at": "2026-01-01T00:00:00+00:00",
            },
        ]
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseChunkEdgesStorage()

    edges = await storage.list_edges_for_chunks(user_jwt="t", chunk_ids=["c1"])

    assert [e.id for e in edges] == ["edge-1"]
