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

REINFORCEMENT_INCREMENT = 1.0  # added to weight per shared retrieval —
# a reasonable, easy-to-retune default, same category as retrieve.py's
# RRF_K or graph/cluster.py's choose_k heuristic.
EXPLICIT_LINK_WEIGHT = 5.0  # a user's deliberate link starts well above
# what a handful of coincidental co-retrievals would reach, so it reads
# as meaningfully stronger on the graph from the moment it's drawn.
DECAY_HALF_LIFE_HOURS = 24 * 7  # one week — an edge untouched for a
# week reads at half its reinforced weight; never applied to is_explicit
# edges.


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


class SupabaseChunkEdgesStorage:
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
        async with httpx.AsyncClient() as client:
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
        async with httpx.AsyncClient() as client:
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
        async with httpx.AsyncClient() as client:
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


_storage: ChunkEdgesStorage = SupabaseChunkEdgesStorage()


def get_chunk_edges_storage() -> ChunkEdgesStorage:
    return _storage


def set_chunk_edges_storage(storage: ChunkEdgesStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage
