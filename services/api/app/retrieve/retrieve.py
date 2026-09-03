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

Fixed post-launch: image chunks (extract.py leaves their `content`
permanently empty) were surviving vector_search/rrf_fuse on a real
embedding, then almost always dying at rerank — a text reranker scored
against an empty string reads as "not relevant" and RELEVANCE_FLOOR
drops it, so a correctly-embedded image essentially never reached a
chat answer or the graph's retrieved-chunk pulse. See
retrieve/image_caption.py — a query-time caption stands in for the
missing text right before rerank.

Stage 7.7 — resilience: query rewrite and HyDE already degrade
gracefully on failure (see rewrite.py/hyde.py); vector_search,
fts_search, and rerank used to be the exception — any RetrieveError
from any of the three propagated straight out of retrieve() and killed
the whole turn. Now all three catch their own RetrieveError and
degrade instead: one search leg failing just means the other leg's
results carry the whole fusion (both failing falls through to the
existing "no fused ids" path — sealed matches, or an empty result —
same code that already runs for a genuinely empty vault, no new
branch needed); a rerank outage returns the top FINAL_TOP_K candidates
in un-reranked RRF-fused order instead of failing outright, skipping
RELEVANCE_FLOOR (a Cohere-relevance-scale threshold that has no
meaning without a Cohere score) since "some real results, unranked"
beats no answer at all.
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol


from app.core.http_client import CachedHttpClientMixin
from app.core.sealed_storage import SealedStorageError, get_sealed_storage
from app.core.tracing import get_tracer
from app.ingest.embed import get_embed_client
from app.retrieve.hyde import generate_hypothetical_answer
from app.retrieve.image_caption import caption_image
from app.retrieve.rewrite import rewrite_query

logger = logging.getLogger(__name__)

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


@dataclass
class UnlockedDocument:
    """Stage 3.4 — the caller's proof of an active unlock for one sealed
    document, re-supplied for this single retrieve() call. Mirrors
    unseal()'s own inputs exactly (Stage 3.3): a claim_id plus the
    derived key, never anything persisted server-side."""
    document_id: str
    claim_id: str
    key_b64: str


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


class CohereRerankClient(CachedHttpClientMixin):
    def __init__(self) -> None:
        self._api_key = os.environ.get("COHERE_API_KEY", "")

    async def rerank(
        self, *, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        client = self._client()
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


class SupabaseRetrieveStorage(CachedHttpClientMixin):
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
        client = self._client()
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
        client = self._client()
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


async def _sealed_exact_matches(
    *,
    user_jwt: str,
    user_id: str,
    query: str,
    unlocked: list[UnlockedDocument],
) -> list[RetrievedChunk]:
    """Stage 3.4 — the only path by which sealed content can ever appear
    in a retrieval result at all: the caller must hold a currently-valid
    unlock claim (Stage 3.3 enforces scope + server-side expiry there,
    not here) and re-supply the derived key for this call, same as a
    direct unseal(). Matching is exact-phrase (case-insensitive
    substring), not semantic — sealed content is never vectorized (Stage
    3.1), so there is no embedding to rank it against. An invalid,
    expired, or mis-scoped claim yields zero matches for that document
    rather than failing the whole turn — same "degrade, don't crash"
    posture as clustering placement elsewhere in this codebase."""
    storage = get_sealed_storage()
    query_lower = query.lower()
    matches: list[RetrievedChunk] = []
    for doc in unlocked:
        try:
            chunks = await storage.unseal_document(
                user_jwt=user_jwt,
                user_id=user_id,
                document_id=doc.document_id,
                claim_id=doc.claim_id,
                key_b64=doc.key_b64,
            )
        except SealedStorageError:
            continue
        for chunk in chunks:
            if query_lower in chunk["content"].lower():
                matches.append(
                    RetrievedChunk(
                        chunk_id=f"{doc.document_id}:{chunk['ordinal']}",
                        document_id=doc.document_id,
                        ordinal=chunk["ordinal"],
                        content=chunk["content"],
                        meta={},
                        relevance_score=1.0,
                    )
                )
    return matches


async def retrieve(
    *,
    user_jwt: str,
    query: str,
    user_id: str | None = None,
    unlocked: list[UnlockedDocument] | None = None,
    recent_messages: list[dict[str, str]] | None = None,
    use_hyde: bool = False,
) -> list[RetrievedChunk]:
    """Five of Stage 1.8's six expected spans live here — embed_query,
    vector_search, fts_search, rrf_fuse, rerank — one per real step in
    this pipeline, in call order (the sixth, generate, is in
    chat/generate.py, since retrieve() has no generation of its own).
    Each span nests under whatever trace chat/stream.py's root span
    opened, via Langfuse's automatic OpenTelemetry context propagation —
    retrieve() doesn't need to know a trace exists at all. Safe when no
    trace is active (e.g. every existing unit test, none of which set
    Langfuse env vars): get_tracer() returns a client whose span context
    managers are no-ops in that case, confirmed live (Stage 1.8
    conversation record) — never raises, never changes retrieve()'s
    actual return value.

    Stage 5.1 — `recent_messages`, when given, runs one cheap rewrite
    call before anything below to resolve pronouns/vague references
    against that history (see retrieve/rewrite.py). Deliberately not
    given its own Langfuse span — Stage 1.8's six-span shape is a fixed,
    regression-tested contract (test_stage_1_8_tracing.py asserts the
    exact span list), and this stage's own exit criteria doesn't call
    for tracing the rewrite step. The rewritten text (or the original
    `query`, unchanged, if rewriting was skipped or failed) is what
    actually gets embedded/searched/reranked below; `_sealed_exact_matches`
    still matches against the caller's real, literal `query` — an
    exact-phrase check against sealed content shouldn't be run against a
    paraphrase.

    Stage 5.2 — `use_hyde`, off by default in this function (its own
    exit criteria called for an A/B-able flag, not a silent default-on
    switch) but explicitly turned on by `chat/stream.py`'s real chat
    turns as of the retrieval-quality pass: when True, one more cheap
    generation call writes a short hypothetical answer to
    `effective_query` (see retrieve/hyde.py), and *that* — not the real
    query — is what gets embedded for vector search specifically. FTS
    and rerank still use `effective_query`: a hypothetical passage may
    not contain the literal keywords the user typed, and rerank should
    judge relevance against what was actually asked, not a guess at the
    answer. A failed or empty hypothetical falls back to embedding
    `effective_query` exactly as if `use_hyde` were False."""
    storage = get_retrieve_storage()
    embed_client = get_embed_client()
    rerank_client = get_rerank_client()
    tracer = get_tracer()

    effective_query = (
        await rewrite_query(query=query, recent_messages=recent_messages)
        if recent_messages
        else query
    )

    hyde_text = await generate_hypothetical_answer(query=effective_query) if use_hyde else None

    with tracer.start_as_current_observation(
        as_type="span",
        name="embed_query",
        input={"query": effective_query, "hyde": hyde_text is not None},
    ) as span:
        # Jina v5's retrieval is an asymmetric bi-encoder — the query side
        # and the indexed-passage side use different task-specific LoRA
        # adapters. Using the wrong one (or none, the bug this fixed)
        # measurably degrades results, most visibly for image chunks:
        # a generic "explain the image" query embedded without this task
        # ranked a real, correctly-embedded image chunk 16th out of 27
        # total chunks in production — confirmed live, not assumed.
        #
        # Stage 5.2 — a HyDE hypothetical is embedded with
        # "retrieval.passage" instead, not "retrieval.query": it's
        # deliberately document-shaped text, meant to land near real
        # indexed passages, so it goes through the same passage-side
        # adapter those passages were embedded with (see hyde.py's
        # module docstring for why this is the detail that makes HyDE
        # actually work, not just a stylistic choice).
        if hyde_text is not None:
            query_embedding = await embed_client.embed_text(hyde_text, task="retrieval.passage")
        else:
            query_embedding = await embed_client.embed_text(
                effective_query, task="retrieval.query"
            )
        span.update(output={"dimensions": len(query_embedding)})

    # Vector search is scoped to documents embedded by the same provider
    # as the query itself (always the primary client — see embed.py's
    # module docstring for why fallback doesn't apply at query time).
    # A document that fell back to Voyage/Cohere lives in a different
    # vector space and must not be compared against this query vector.
    with tracer.start_as_current_observation(
        as_type="span", name="vector_search", input={"match_count": VECTOR_CANDIDATES}
    ) as span:
        try:
            vector_results = await storage.vector_search(
                user_jwt=user_jwt,
                query_embedding=query_embedding,
                match_count=VECTOR_CANDIDATES,
                primary_provider=embed_client.provider,
            )
        except RetrieveError:
            # Degrade, don't crash — same posture as rewrite_query/
            # generate_hypothetical_answer: one search leg failing
            # shouldn't fail the whole turn when the other leg might
            # still carry it. fts_search below runs regardless.
            logger.exception("vector_search failed, degrading to FTS-only results")
            vector_results = []
        span.update(output={"result_count": len(vector_results)})

    with tracer.start_as_current_observation(
        as_type="span", name="fts_search", input={"match_count": FTS_CANDIDATES}
    ) as span:
        try:
            fts_results = await storage.fts_search(
                user_jwt=user_jwt, query_text=effective_query, match_count=FTS_CANDIDATES
            )
        except RetrieveError:
            logger.exception("fts_search failed, degrading to vector-only results")
            fts_results = []
        span.update(output={"result_count": len(fts_results)})

    by_id: dict[str, dict[str, Any]] = {r["id"]: r for r in vector_results}
    by_id.update({r["id"]: r for r in fts_results})

    with tracer.start_as_current_observation(as_type="span", name="rrf_fuse") as span:
        fused_ids = rrf_fuse(
            [r["id"] for r in vector_results], [r["id"] for r in fts_results]
        )[:RERANK_TOP_N]
        span.update(output={"fused_ids": fused_ids})
    if not fused_ids:
        if unlocked:
            return await _sealed_exact_matches(
                user_jwt=user_jwt, user_id=user_id or "", query=query, unlocked=unlocked
            )
        return []

    # `dict(...)` copies — image chunks (empty `content`, extract.py never
    # captions them) get a captioned stand-in filled in below for rerank
    # scoring and citation text; mutating the shared row objects from
    # by_id/vector_results/fts_results in place would be a surprising
    # side effect for no reason.
    candidates = [dict(by_id[chunk_id]) for chunk_id in fused_ids]

    # Cohere's reranker is text-only — scored against an empty string,
    # an image chunk vector_search legitimately found reads as "not
    # relevant" and gets dropped by RELEVANCE_FLOOR before ever reaching
    # the caller. One caption per distinct document (not persisted, only
    # for this call) stands in for the missing text. Best-effort: a
    # caption that fails to generate just leaves that candidate's content
    # empty exactly as before, same "degrade, don't crash" contract as
    # rewrite_query/generate_hypothetical_answer above — never a new way
    # for retrieve() itself to fail. Deliberately not given its own
    # Langfuse span, same reasoning as the rewrite step: Stage 1.8's
    # six-span shape is a fixed, regression-tested contract.
    uncaptioned_document_ids = {c["document_id"] for c in candidates if not c["content"]}
    if uncaptioned_document_ids:
        captions = dict(
            zip(
                uncaptioned_document_ids,
                await asyncio.gather(
                    *(
                        caption_image(user_jwt=user_jwt, document_id=document_id)
                        for document_id in uncaptioned_document_ids
                    )
                ),
            )
        )
        for candidate in candidates:
            caption = captions.get(candidate["document_id"])
            if not candidate["content"] and caption:
                candidate["content"] = caption

    with tracer.start_as_current_observation(
        as_type="span",
        name="rerank",
        input={"query": effective_query, "candidate_count": len(candidates)},
    ) as span:
        try:
            rerank_results = await rerank_client.rerank(
                query=effective_query,
                documents=[c["content"] for c in candidates],
                top_n=FINAL_TOP_K,
            )
            span.update(output={"result_count": len(rerank_results)})
        except RetrieveError:
            # Degrade to un-reranked RRF order rather than fail the
            # whole turn on a Cohere outage — "some real results,
            # unranked" beats no answer at all. RELEVANCE_FLOOR is a
            # Cohere relevance-score-scale threshold and has no meaning
            # without a real Cohere score, so it's skipped here, not
            # applied to a placeholder.
            logger.exception("rerank failed, degrading to un-reranked RRF order")
            span.update(output={"result_count": None, "degraded": True})
            rerank_results = None

    results: list[RetrievedChunk] = []
    if rerank_results is None:
        for candidate in candidates[:FINAL_TOP_K]:
            results.append(
                RetrievedChunk(
                    chunk_id=candidate["id"],
                    document_id=candidate["document_id"],
                    ordinal=candidate["ordinal"],
                    content=candidate["content"],
                    meta=candidate["meta"],
                    relevance_score=1.0,
                )
            )
    else:
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

    if unlocked:
        results.extend(
            await _sealed_exact_matches(
                user_jwt=user_jwt, user_id=user_id or "", query=query, unlocked=unlocked
            )
        )
    return results
