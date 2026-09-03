"""Stage 5.3 — associative memory graph (persistent chunk edges).

Distinct from Stage 2.2's `document_edges` (kNN neighbors recomputed
whole-scale at each recluster, from centroid vectors — a similarity
structure) — `chunk_edges` is a usage structure: which chunks actually
got pulled into the same answer together, reinforced turn by turn
("chunks that fire together wire together"). The two coexist; Stage 5.4
renders both as separate layers.

Two edge sources, both landing in this one table:
- **Retrieval co-occurrence** (`reinforce_co_retrieval`, the primary
  source — free, derived entirely from data `chat/stream.py` already
  computes): every real chat turn's final chunk set reinforces every
  pair in it. No new ingest work, no LLM call.
- **Explicit user-drawn links** (`create_explicit_link`): a caller
  asserts a link between two of their own chunks directly. Stored with
  `is_explicit=True` and never decayed.

Undirected by construction: `_canonical_pair` always orders the two
chunk ids the same way regardless of retrieval order, so the table's
`unique(user_id, source_chunk_id, target_chunk_id)` constraint is what
actually prevents a pair from ever being represented by two rows — not
application discipline alone.

No decay column, no scheduled job (this project's Render free tier has
no room for a background worker outside the request cycle — see
CLAUDE.md). `decay_weight` is a pure function applied at *read* time:
a pair's effective weight is `weight * 0.5 ** (hours_since_reinforced /
DECAY_HALF_LIFE_HOURS)`, computed fresh whenever edges are fetched
(the next real request that reads them — Stage 5.4's graph rendering,
once built) rather than written back on a schedule. An `is_explicit`
edge's stored weight is always returned unchanged, never decayed.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Protocol

import httpx
from fastapi import HTTPException

from app.core.http_client import CachedHttpClientMixin

REINFORCEMENT_INCREMENT = 1.0  # added to weight per shared retrieval —
# a reasonable, easy-to-retune default, same category as retrieve.py's
# RRF_K or graph/cluster.py's choose_k heuristic.
EXPLICIT_LINK_WEIGHT = 5.0  # a user's deliberate link starts well above
# what a handful of coincidental co-retrievals would reach, so it reads
# as meaningfully stronger on the graph from the moment it's drawn.
DECAY_HALF_LIFE_HOURS = 24 * 7  # one week — an edge untouched for a
# week reads at half its reinforced weight; never applied to is_explicit
# edges.
MIN_RENDERED_WEIGHT = REINFORCEMENT_INCREMENT * 1.5  # a document edge
# only renders once it's been reinforced more than once (or is explicit,
# which always clears this). Without a floor here, retrieve.py's
# FINAL_TOP_K=5 means a *single* question against a small vault already
# touches half its documents, and every pairwise combination among those
# five chunks becomes a permanent, fully-opaque edge from that one
# query — reported live as "all nodes connected" after asking one
# question. Reinforcement across at least two separate retrievals is a
# real usage signal; one lucky co-occurrence in a single answer isn't.


def _canonical_pair(chunk_id_a: str, chunk_id_b: str) -> tuple[str, str]:
    return (chunk_id_a, chunk_id_b) if chunk_id_a < chunk_id_b else (chunk_id_b, chunk_id_a)


def decay_weight(*, weight: float, last_reinforced_at: datetime, now: datetime) -> float:
    hours_elapsed = max(0.0, (now - last_reinforced_at).total_seconds() / 3600)
    return weight * (0.5 ** (hours_elapsed / DECAY_HALF_LIFE_HOURS))


@dataclass
class ChunkEdge:
    id: str
    source_chunk_id: str
    target_chunk_id: str
    weight: float
    co_retrieval_count: int
    is_explicit: bool
    last_reinforced_at: datetime

    def effective_weight(self, *, now: datetime | None = None) -> float:
        if self.is_explicit:
            return self.weight
        return decay_weight(
            weight=self.weight,
            last_reinforced_at=self.last_reinforced_at,
            now=now or datetime.now(timezone.utc),
        )


class ChunkEdgesError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class DocumentAssociativeEdge:
    document_id: str
    neighbor_document_id: str
    weight: float
    is_explicit: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "neighbor_document_id": self.neighbor_document_id,
            "weight": round(self.weight, 6),
            "is_explicit": self.is_explicit,
        }


def aggregate_to_document_edges(
    edges: list[ChunkEdge],
    chunk_to_document: dict[str, str],
    *,
    now: datetime | None = None,
) -> list[DocumentAssociativeEdge]:
    """Stage 5.4 — the main graph shows document nodes, not chunk nodes,
    so a chunk_edges pair only becomes a renderable edge once resolved
    to its two parent documents. Pure function (no I/O) so this can be
    tested directly against fixture edges/chunk-to-document maps, same
    "pure logic separated from storage" pattern as decay_weight/
    _canonical_pair above.

    A chunk pair whose two chunks belong to the *same* document is
    dropped — that's not a document-level edge, it's noise the main
    graph has no way to render (both ends would land on one node).
    Multiple chunk pairs between the same two documents sum into one
    edge, using each chunk_edge's real effective (decayed) weight, not
    the raw stored one — same decay-at-read-time principle Stage 5.3
    already established. An aggregated edge is marked is_explicit if
    *any* contributing chunk pair was an explicit user-drawn link, so a
    single deliberate link between two chunks still reads as a strong,
    non-decaying connection between their documents.
    """
    totals: dict[tuple[str, str], float] = {}
    any_explicit: dict[tuple[str, str], bool] = {}
    for edge in edges:
        doc_a = chunk_to_document.get(edge.source_chunk_id)
        doc_b = chunk_to_document.get(edge.target_chunk_id)
        if not doc_a or not doc_b or doc_a == doc_b:
            continue
        key = (doc_a, doc_b) if doc_a < doc_b else (doc_b, doc_a)
        totals[key] = totals.get(key, 0.0) + edge.effective_weight(now=now)
        any_explicit[key] = any_explicit.get(key, False) or edge.is_explicit

    return [
        DocumentAssociativeEdge(
            document_id=doc_a,
            neighbor_document_id=doc_b,
            weight=weight,
            is_explicit=any_explicit[(doc_a, doc_b)],
        )
        for (doc_a, doc_b), weight in totals.items()
    ]


class ChunkEdgesStorage(Protocol):
    async def reinforce_co_retrieval(
        self, *, user_jwt: str, user_id: str, chunk_ids: list[str]
    ) -> None: ...

    async def create_explicit_link(
        self, *, user_jwt: str, user_id: str, chunk_id_a: str, chunk_id_b: str
    ) -> ChunkEdge | None: ...

    async def list_edges_for_chunks(
        self, *, user_jwt: str, chunk_ids: list[str]
    ) -> list[ChunkEdge]: ...

    async def list_all_edges(self, *, user_jwt: str) -> list[ChunkEdge]: ...

    async def resolve_chunk_documents(
        self, *, user_jwt: str, chunk_ids: list[str]
    ) -> dict[str, str]: ...


def _parse_row(row: dict[str, Any]) -> ChunkEdge:
    last_reinforced_at = row["last_reinforced_at"]
    if isinstance(last_reinforced_at, str):
        last_reinforced_at = datetime.fromisoformat(last_reinforced_at.replace("Z", "+00:00"))
    return ChunkEdge(
        id=row["id"],
        source_chunk_id=row["source_chunk_id"],
        target_chunk_id=row["target_chunk_id"],
        weight=row["weight"],
        co_retrieval_count=row["co_retrieval_count"],
        is_explicit=row["is_explicit"],
        last_reinforced_at=last_reinforced_at,
    )


class SupabaseChunkEdgesStorage(CachedHttpClientMixin):
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {user_jwt}",
            "Content-Type": "application/json",
        }

    async def _get_pair(
        self, client: httpx.AsyncClient, user_jwt: str, source: str, target: str
    ) -> dict[str, Any] | None:
        response = await client.get(
            f"{self._supabase_url}/rest/v1/chunk_edges",
            headers=self._headers(user_jwt),
            params={
                "source_chunk_id": f"eq.{source}",
                "target_chunk_id": f"eq.{target}",
                "select": "*",
            },
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="chunk_edge_lookup_failed")
        rows = response.json()
        return rows[0] if rows else None

    async def reinforce_co_retrieval(
        self, *, user_jwt: str, user_id: str, chunk_ids: list[str]
    ) -> None:
        # Fewer than two distinct chunks retrieved this turn — no pair to
        # reinforce. Not an error, just nothing to do.
        distinct_ids = sorted(set(chunk_ids))
        if len(distinct_ids) < 2:
            return

        now = datetime.now(timezone.utc).isoformat()
        client = self._client()
        for chunk_id_a, chunk_id_b in combinations(distinct_ids, 2):
            source, target = _canonical_pair(chunk_id_a, chunk_id_b)
            existing = await self._get_pair(client, user_jwt, source, target)
            if existing is None:
                await client.post(
                    f"{self._supabase_url}/rest/v1/chunk_edges",
                    headers=self._headers(user_jwt),
                    json={
                        "user_id": user_id,
                        "source_chunk_id": source,
                        "target_chunk_id": target,
                        "weight": REINFORCEMENT_INCREMENT,
                        "co_retrieval_count": 1,
                        "is_explicit": False,
                        "last_reinforced_at": now,
                    },
                )
            elif not existing["is_explicit"]:
                # An explicit link is never touched by co-retrieval —
                # it keeps its fixed weight regardless of how often
                # the same pair also happens to be retrieved together.
                await client.patch(
                    f"{self._supabase_url}/rest/v1/chunk_edges",
                    headers=self._headers(user_jwt),
                    params={"id": f"eq.{existing['id']}"},
                    json={
                        "weight": existing["weight"] + REINFORCEMENT_INCREMENT,
                        "co_retrieval_count": existing["co_retrieval_count"] + 1,
                        "last_reinforced_at": now,
                    },
                )

    async def create_explicit_link(
        self, *, user_jwt: str, user_id: str, chunk_id_a: str, chunk_id_b: str
    ) -> ChunkEdge | None:
        source, target = _canonical_pair(chunk_id_a, chunk_id_b)
        client = self._client()
        # Both chunks must actually be the caller's own — an RLS-scoped
        # lookup, same "explicit ownership check before a cross-
        # reference insert" pattern kanban_storage.create_card already
        # uses for board_id. A sealed document's chunk id can never
        # appear here either: sealing deletes the chunks row entirely
        # (Stage 3.3), so the lookup below just comes back short.
        chunks_resp = await client.get(
            f"{self._supabase_url}/rest/v1/chunks",
            headers=self._headers(user_jwt),
            params={"id": f"in.({source},{target})", "select": "id"},
        )
        if chunks_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="chunk_lookup_failed")
        if len(chunks_resp.json()) != 2:
            return None

        response = await client.post(
            f"{self._supabase_url}/rest/v1/chunk_edges",
            headers={**self._headers(user_jwt), "Prefer": "return=representation,resolution=merge-duplicates"},
            params={"on_conflict": "user_id,source_chunk_id,target_chunk_id"},
            json={
                "user_id": user_id,
                "source_chunk_id": source,
                "target_chunk_id": target,
                "weight": EXPLICIT_LINK_WEIGHT,
                "co_retrieval_count": 0,
                "is_explicit": True,
                "last_reinforced_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="chunk_edge_create_failed")
        rows = response.json()
        return _parse_row(rows[0]) if rows else None

    async def list_edges_for_chunks(
        self, *, user_jwt: str, chunk_ids: list[str]
    ) -> list[ChunkEdge]:
        if not chunk_ids:
            return []
        in_list = ",".join(sorted(set(chunk_ids)))
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/rest/v1/chunk_edges",
            headers=self._headers(user_jwt),
            params={
                "or": f"(source_chunk_id.in.({in_list}),target_chunk_id.in.({in_list}))",
                "select": "*",
            },
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="chunk_edges_list_failed")
        return [_parse_row(r) for r in response.json()]

    async def list_all_edges(self, *, user_jwt: str) -> list[ChunkEdge]:
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/rest/v1/chunk_edges",
            headers=self._headers(user_jwt),
            params={"select": "*"},
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="chunk_edges_list_failed")
        return [_parse_row(r) for r in response.json()]

    async def resolve_chunk_documents(
        self, *, user_jwt: str, chunk_ids: list[str]
    ) -> dict[str, str]:
        if not chunk_ids:
            return {}
        in_list = ",".join(sorted(set(chunk_ids)))
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/rest/v1/chunks",
            headers=self._headers(user_jwt),
            params={"id": f"in.({in_list})", "select": "id,document_id"},
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="resolve_chunk_documents_failed")
        return {row["id"]: row["document_id"] for row in response.json()}


async def get_associative_document_edges(*, user_jwt: str) -> list[dict[str, Any]]:
    """Stage 5.4 — GET /graph/edges?include=associative's real logic:
    fetch every one of the caller's chunk_edges, resolve each chunk to
    its document, and aggregate into document-level edges via the pure
    aggregate_to_document_edges above. Deliberately fetches every
    chunk_edges row rather than scoping to a specific document set —
    this project's scale (a personal vault, not a multi-tenant SaaS)
    makes that the simplest correct thing, same posture Stage 2.1's
    clustering job already takes toward "recompute over everything"."""
    storage = get_chunk_edges_storage()
    edges = await storage.list_all_edges(user_jwt=user_jwt)
    if not edges:
        return []
    chunk_ids = {e.source_chunk_id for e in edges} | {e.target_chunk_id for e in edges}
    chunk_to_document = await storage.resolve_chunk_documents(
        user_jwt=user_jwt, chunk_ids=list(chunk_ids)
    )
    return [
        e.to_dict()
        for e in aggregate_to_document_edges(edges, chunk_to_document)
        if e.weight >= MIN_RENDERED_WEIGHT
    ]


_storage: ChunkEdgesStorage = SupabaseChunkEdgesStorage()


def get_chunk_edges_storage() -> ChunkEdgesStorage:
    return _storage


def set_chunk_edges_storage(storage: ChunkEdgesStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage
