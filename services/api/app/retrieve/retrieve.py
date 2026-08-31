"""Stage 1.5 — hybrid retrieval (vector + FTS, RRF-fused, reranked).

No "Docify" source was available to fork from anywhere in this repo,
despite CLAUDE.md/phases-and-gates.md describing retrieval as forked
from it — built fresh from the documented behavior/exit criteria
instead (confirmed with the user before starting).

Vector search and FTS both go through Postgres RPC functions
(match_chunks_vector, match_chunks_fts — supabase/migrations/0005) since
PostgREST's plain table query syntax can't order by a computed
expression like cosine distance or ts_rank, only real columns. Both
functions are SECURITY INVOKER (Postgres's default), so RLS applies
exactly as it does to direct table access — confirmed live, not
assumed: a cross-user retrieve call surfaces nothing (see conversation
record).

RRF fusion uses k=60, the standard constant from the original
Reciprocal Rank Fusion paper (Cormack, Clarke & Buettcher 2009) — not
an arbitrary choice.

Reranker: Cohere rerank-v4.0-pro — chosen deliberately in Stage 1.5's
conversation (previously left "TBD" in Stage 1.4), current API
confirmed live before writing this code, not from memory.

The relevance floor after rerank — not a forced top-k — is what makes
"no relevant content" return empty rather than always handing back K
results regardless of quality, per this stage's exit criteria.
"""
import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.ingest.embed import get_embed_client

RRF_K = 60  # standard constant from the original RRF paper, not tunable
# in the way the other defaults below are.

VECTOR_CANDIDATES = 20  # how many candidates each retrieval method fetches
FTS_CANDIDATES = 20
RERANK_TOP_N = 10  # how many fused candidates go to the reranker
FINAL_TOP_K = 5  # max results retrieve() returns after rerank
RELEVANCE_FLOOR = 0.2  # Cohere relevance_score is [0,1]; below this a
# result is treated as "not actually relevant" rather than forced into
# the output. Not specified anywhere in the docs — a reasonable default,
# easy to retune, not an architectural decision.

COHERE_RERANK_URL = "https://api.cohere.com/v2/rerank"
COHERE_RERANK_MODEL = "rerank-v4.0-pro"


class RetrieveError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    ordinal: int
    content: str
    meta: dict[str, Any]
    relevance_score: float


def rrf_fuse(*ranked_lists: list[str], k: int = RRF_K) -> list[str]:
    """Pure function, no I/O — given N ranked lists of ids (best first),
    returns a single fused ranking by Reciprocal Rank Fusion score."""
    scores: dict[str, float] = {}
    for ranked_list in ranked_lists:
        for rank, item_id in enumerate(ranked_list, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.keys(), key=lambda item_id: scores[item_id], reverse=True)


class RerankClient(Protocol):
    async def rerank(
        self, *, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        """Returns (original_index, relevance_score) pairs, sorted by
        relevance_score descending."""
        ...


class CohereRerankClient:
    def __init__(self) -> None:
        self._api_key = os.environ.get("COHERE_API_KEY", "")

    async def rerank(
        self, *, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                COHERE_RERANK_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": COHERE_RERANK_MODEL,
                    "query": query,
                    "documents": documents,
                    "top_n": top_n,
                },
            )
        if response.status_code >= 400:
            raise RetrieveError("rerank_failed", response.text)
        return [
            (result["index"], result["relevance_score"])
            for result in response.json()["results"]
        ]


_rerank_client: RerankClient = CohereRerankClient()


def get_rerank_client() -> RerankClient:
    return _rerank_client


def set_rerank_client(client: RerankClient) -> None:
    """Test seam — inject a fake rerank client (deterministic, no network)."""
    global _rerank_client
    _rerank_client = client


class RetrieveStorage(Protocol):
    async def vector_search(
        self,
        *,
        user_jwt: str,
        query_embedding: list[float],
        match_count: int,
        primary_provider: str,
    ) -> list[dict[str, Any]]: ...
    async def fts_search(
        self, *, user_jwt: str, query_text: str, match_count: int
    ) -> list[dict[str, Any]]: ...


class SupabaseRetrieveStorage:
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {user_jwt}",
            "Content-Type": "application/json",
        }

    async def vector_search(
        self,
        *,
        user_jwt: str,
        query_embedding: list[float],
        match_count: int,
        primary_provider: str,
    ) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._supabase_url}/rest/v1/rpc/match_chunks_vector",
                headers=self._headers(user_jwt),
                json={
                    "query_embedding": query_embedding,
                    "match_count": match_count,
                    "primary_provider": primary_provider,
                },
            )
        if response.status_code >= 400:
            raise RetrieveError("vector_search_failed", response.text)
        return response.json()

    async def fts_search(
        self, *, user_jwt: str, query_text: str, match_count: int
    ) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._supabase_url}/rest/v1/rpc/match_chunks_fts",
                headers=self._headers(user_jwt),
                json={"query_text": query_text, "match_count": match_count},
            )
        if response.status_code >= 400:
            raise RetrieveError("fts_search_failed", response.text)
        return response.json()


_storage: RetrieveStorage = SupabaseRetrieveStorage()


def get_retrieve_storage() -> RetrieveStorage:
    return _storage


def set_retrieve_storage(storage: RetrieveStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage


async def retrieve(*, user_jwt: str, query: str) -> list[RetrievedChunk]:
    storage = get_retrieve_storage()
    embed_client = get_embed_client()
    rerank_client = get_rerank_client()

    query_embedding = await embed_client.embed_text(query)

    # Vector search is scoped to documents embedded by the same provider
    # as the query itself (always the primary client — see embed.py's
    # module docstring for why fallback doesn't apply at query time).
    # A document that fell back to Voyage/Cohere lives in a different
    # vector space and must not be compared against this query vector.
    vector_results = await storage.vector_search(
        user_jwt=user_jwt,
        query_embedding=query_embedding,
        match_count=VECTOR_CANDIDATES,
        primary_provider=embed_client.provider,
    )
    fts_results = await storage.fts_search(
        user_jwt=user_jwt, query_text=query, match_count=FTS_CANDIDATES
    )

    by_id: dict[str, dict[str, Any]] = {r["id"]: r for r in vector_results}
    by_id.update({r["id"]: r for r in fts_results})

    fused_ids = rrf_fuse(
        [r["id"] for r in vector_results], [r["id"] for r in fts_results]
    )[:RERANK_TOP_N]
    if not fused_ids:
        return []

    candidates = [by_id[chunk_id] for chunk_id in fused_ids]
    rerank_results = await rerank_client.rerank(
        query=query,
        documents=[c["content"] for c in candidates],
        top_n=FINAL_TOP_K,
    )

    results: list[RetrievedChunk] = []
    for index, score in rerank_results:
        if score < RELEVANCE_FLOOR:
            continue
        candidate = candidates[index]
        results.append(
            RetrievedChunk(
                chunk_id=candidate["id"],
                document_id=candidate["document_id"],
                ordinal=candidate["ordinal"],
                content=candidate["content"],
                meta=candidate["meta"],
                relevance_score=score,
            )
        )
    return results
