"""Stage 1.5 — hybrid retrieval (vector + FTS, RRF-fused, reranked).

Exit criteria:
- Fixture query with a known-relevant chunk returns that chunk in the
  top 3 post-rerank.
- RRF fusion unit test: given two synthetic ranked lists, output order
  matches hand-computed expected fusion.
- A query with no relevant content returns an empty/low-confidence
  result, not a forced top-k.

No "Docify" source was available anywhere in this repo to fork from —
built fresh from the documented behavior instead (confirmed with the
user). The "known-relevant chunk in top 3" test uses fake embed/rerank
clients with realistic scoring so it's deterministic; real semantic
relevance against the live Jina/Cohere APIs is verified separately (see
conversation record) since that depends on actual model behavior, not
something a unit test should assert.
"""
import pytest

from app.ingest import embed as embed_module
from app.retrieve import retrieve as retrieve_module
from app.retrieve.retrieve import (
    FINAL_TOP_K,
    RELEVANCE_FLOOR,
    RRF_K,
    RetrieveError,
    retrieve,
    rrf_fuse,
)

# --- RRF fusion (pure function, hand-computed) --------------------------------


def test_rrf_fuse_matches_hand_computed_expected_order():
    # list_a: A, B, C (ranks 1,2,3)   list_b: B, C, A (ranks 1,2,3)
    # score(A) = 1/61 + 1/63 = 0.0322664...
    # score(B) = 1/62 + 1/61 = 0.0325224...  <- highest
    # score(C) = 1/63 + 1/62 = 0.0320020...  <- lowest
    # Expected fused order: B, A, C
    list_a = ["A", "B", "C"]
    list_b = ["B", "C", "A"]
    assert rrf_fuse(list_a, list_b, k=RRF_K) == ["B", "A", "C"]


def test_rrf_fuse_item_in_both_lists_outranks_item_in_only_one():
    list_a = ["X", "Y"]
    list_b = ["X", "Z"]
    fused = rrf_fuse(list_a, list_b, k=RRF_K)
    assert fused[0] == "X"  # appears at rank 1 in both lists


def test_rrf_fuse_empty_lists_returns_empty():
    assert rrf_fuse([], [], k=RRF_K) == []


def test_rrf_fuse_single_list_preserves_its_order():
    assert rrf_fuse(["A", "B", "C"], []) == ["A", "B", "C"]


# --- retrieve() orchestration --------------------------------------------------


class _FakeEmbedClient:
    provider = "jina"

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        return [0.1] * 1024

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
        raise NotImplementedError


class _FakeRerankClient:
    """Scores documents by a simple deterministic rule the tests control
    via a lookup table, so "known-relevant chunk ranks in top 3" is
    provable without depending on a real model's actual judgment."""

    def __init__(self, scores_by_content: dict[str, float]):
        self.scores_by_content = scores_by_content
        self.last_call: dict | None = None

    async def rerank(self, *, query, documents, top_n):
        self.last_call = {"query": query, "documents": documents, "top_n": top_n}
        scored = [
            (i, self.scores_by_content.get(doc, 0.0)) for i, doc in enumerate(documents)
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_n]


class _FakeRetrieveStorage:
    def __init__(
        self,
        *,
        vector_results: list[dict],
        fts_results: list[dict],
        fail_vector: bool = False,
        fail_fts: bool = False,
    ):
        self.vector_results = vector_results
        self.fts_results = fts_results
        self.fail_vector = fail_vector
        self.fail_fts = fail_fts

    async def vector_search(self, *, user_jwt, query_embedding, match_count, primary_provider):
        if self.fail_vector:
            raise RetrieveError("vector_search_failed", "simulated vector search outage")
        return self.vector_results[:match_count]

    async def fts_search(self, *, user_jwt, query_text, match_count):
        if self.fail_fts:
            raise RetrieveError("fts_search_failed", "simulated FTS outage")
        return self.fts_results[:match_count]


class _FailingRerankClient:
    async def rerank(self, *, query, documents, top_n):
        raise RetrieveError("rerank_failed", "simulated rerank outage")


def _chunk(chunk_id, content, ordinal=0, meta=None):
    return {
        "id": chunk_id,
        "document_id": f"doc-for-{chunk_id}",
        "ordinal": ordinal,
        "content": content,
        "meta": meta or {},
    }


@pytest.fixture(autouse=True)
def _reset():
    yield
    embed_module.set_embed_client(embed_module.JinaEmbedClient())
    retrieve_module.set_rerank_client(retrieve_module.CohereRerankClient())
    retrieve_module.set_retrieve_storage(retrieve_module.SupabaseRetrieveStorage())


@pytest.mark.asyncio
async def test_known_relevant_chunk_appears_in_top_3():
    relevant = _chunk("relevant-1", "Cerebro seals files behind a passphrase")
    distractor_a = _chunk("noise-1", "Bananas are a good source of potassium")
    distractor_b = _chunk("noise-2", "The weather in Tokyo is mild in spring")
    distractor_c = _chunk("noise-3", "Rate limits reset after the window elapses")
    distractor_d = _chunk("noise-4", "Pikepdf optimizes PDF structure losslessly")

    all_chunks = [relevant, distractor_a, distractor_b, distractor_c, distractor_d]
    storage = _FakeRetrieveStorage(vector_results=all_chunks, fts_results=[distractor_a, relevant])
    rerank = _FakeRerankClient(
        scores_by_content={relevant["content"]: 0.95, **{c["content"]: 0.1 for c in all_chunks[1:]}}
    )

    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="how do sealed files work")

    top_3_ids = [r.chunk_id for r in results[:3]]
    assert "relevant-1" in top_3_ids
    assert results[0].chunk_id == "relevant-1"  # highest score, should be #1


@pytest.mark.asyncio
async def test_query_with_no_relevant_content_returns_empty_not_forced_top_k():
    chunks = [_chunk(f"c{i}", f"unrelated content {i}") for i in range(5)]
    storage = _FakeRetrieveStorage(vector_results=chunks, fts_results=[])
    # Every candidate scores below the relevance floor.
    rerank = _FakeRerankClient(scores_by_content={c["content"]: 0.01 for c in chunks})

    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="something completely unrelated")

    assert results == [], "low-relevance candidates must not be forced into the output"


@pytest.mark.asyncio
async def test_empty_index_returns_empty_without_calling_rerank():
    storage = _FakeRetrieveStorage(vector_results=[], fts_results=[])
    rerank = _FakeRerankClient(scores_by_content={})

    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="anything")

    assert results == []
    assert rerank.last_call is None  # never worth calling rerank on nothing


@pytest.mark.asyncio
async def test_relevance_floor_is_applied_per_result_not_all_or_nothing():
    a = _chunk("a", "highly relevant content")
    b = _chunk("b", "somewhat relevant content")
    c = _chunk("c", "not relevant at all")
    storage = _FakeRetrieveStorage(vector_results=[a, b, c], fts_results=[])
    rerank = _FakeRerankClient(
        scores_by_content={
            a["content"]: 0.9,
            b["content"]: 0.5,
            c["content"]: RELEVANCE_FLOOR - 0.01,  # just under the floor
        }
    )

    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="q")

    assert [r.chunk_id for r in results] == ["a", "b"]


@pytest.mark.asyncio
async def test_image_chunk_with_empty_content_is_captioned_before_rerank(monkeypatch):
    """The bug: an image chunk's `content` is always "" (extract.py never
    captions it), so the old code fed the reranker an empty string and
    RELEVANCE_FLOOR dropped it — a real, correctly-embedded image chunk
    never reached the caller. This proves the fix: a captioned stand-in
    reaches the reranker instead, and a real caption lets an image chunk
    rank exactly like any text chunk would."""
    image_chunk = _chunk("img-1", "", meta={"bbox": [0, 0, 100, 100]})
    text_chunk = _chunk("noise-1", "Bananas are a good source of potassium")
    storage = _FakeRetrieveStorage(
        vector_results=[image_chunk, text_chunk], fts_results=[]
    )

    captioned_calls = []

    async def fake_caption_image(*, user_jwt, document_id):
        captioned_calls.append(document_id)
        return "A whiteboard with a project timeline sketched on it"

    monkeypatch.setattr(retrieve_module, "caption_image", fake_caption_image)

    rerank = _FakeRerankClient(
        scores_by_content={
            "A whiteboard with a project timeline sketched on it": 0.9,
            text_chunk["content"]: 0.1,
        }
    )

    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="what's the project timeline")

    assert captioned_calls == [image_chunk["document_id"]]
    assert results[0].chunk_id == "img-1"
    assert results[0].content == "A whiteboard with a project timeline sketched on it"
    # The original row in vector_results must be untouched — retrieve()
    # copies candidates before filling in the caption.
    assert image_chunk["content"] == ""


@pytest.mark.asyncio
async def test_image_chunk_caption_failure_degrades_to_empty_content(monkeypatch):
    """A captioning failure (network error, no signed url, empty model
    output) must never fail retrieve() itself — same "degrade, don't
    crash" contract as rewrite_query/generate_hypothetical_answer."""
    image_chunk = _chunk("img-1", "", meta={"bbox": [0, 0, 100, 100]})
    storage = _FakeRetrieveStorage(vector_results=[image_chunk], fts_results=[])

    async def failing_caption_image(*, user_jwt, document_id):
        return None

    monkeypatch.setattr(retrieve_module, "caption_image", failing_caption_image)

    rerank = _FakeRerankClient(scores_by_content={"": 0.01})

    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="anything")

    assert rerank.last_call["documents"] == [""]
    assert results == []


@pytest.mark.asyncio
async def test_retrieve_never_returns_more_than_final_top_k():
    chunks = [_chunk(f"c{i}", f"relevant content {i}") for i in range(FINAL_TOP_K + 5)]
    storage = _FakeRetrieveStorage(vector_results=chunks, fts_results=[])
    rerank = _FakeRerankClient(scores_by_content={c["content"]: 0.8 for c in chunks})

    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="q")

    assert len(results) <= FINAL_TOP_K


# --- Stage 7.7: retrieval resilience (soft-fail rerank/vector/FTS) -----------


@pytest.mark.asyncio
async def test_rerank_failure_degrades_to_unreranked_rrf_order_not_a_crash():
    chunks = [_chunk(f"c{i}", f"relevant content {i}") for i in range(3)]
    storage = _FakeRetrieveStorage(vector_results=chunks, fts_results=[])

    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(_FailingRerankClient())
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="anything")

    # A real, usable result set — not an exception, not empty — capped
    # at FINAL_TOP_K, in the fused order (RELEVANCE_FLOOR doesn't apply
    # without a real Cohere score).
    assert len(results) == 3
    assert {r.chunk_id for r in results} == {"c0", "c1", "c2"}
    assert all(r.relevance_score == 1.0 for r in results)


@pytest.mark.asyncio
async def test_vector_search_failure_still_returns_fts_leg_results():
    fts_chunk = _chunk("fts-only", "relevant via full text search")
    storage = _FakeRetrieveStorage(
        vector_results=[], fts_results=[fts_chunk], fail_vector=True
    )
    rerank = _FakeRerankClient(scores_by_content={fts_chunk["content"]: 0.9})

    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="anything")

    assert [r.chunk_id for r in results] == ["fts-only"]


@pytest.mark.asyncio
async def test_fts_failure_still_returns_vector_leg_results():
    vector_chunk = _chunk("vector-only", "relevant via vector search")
    storage = _FakeRetrieveStorage(
        vector_results=[vector_chunk], fts_results=[], fail_fts=True
    )
    rerank = _FakeRerankClient(scores_by_content={vector_chunk["content"]: 0.9})

    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="anything")

    assert [r.chunk_id for r in results] == ["vector-only"]


@pytest.mark.asyncio
async def test_both_search_legs_failing_returns_empty_not_a_crash():
    storage = _FakeRetrieveStorage(
        vector_results=[], fts_results=[], fail_vector=True, fail_fts=True
    )
    rerank = _FakeRerankClient(scores_by_content={})

    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="anything")

    assert results == []
    assert rerank.last_call is None  # nothing to rerank once both legs are empty
