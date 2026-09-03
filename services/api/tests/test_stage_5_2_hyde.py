"""Stage 5.2 — HyDE (Hypothetical Document Embeddings). Exercises
generate_hypothetical_answer directly (a monkeypatched
generate_module.run_interaction, no real network), plus retrieve()'s
wiring: use_hyde=True embeds the hypothetical passage (task=
retrieval.passage) instead of the real query for vector search only —
FTS and rerank still see the real (possibly rewritten) query. Off by
default, exactly the pre-5.2 shape when use_hyde is omitted. Stage
1.5's own "known-relevant chunk in top 3" fixture is re-run with HyDE
enabled and must still pass, per this stage's own exit criteria.
"""
import pytest

from app.chat.generate import GenerateError
from app.ingest import embed as embed_module
from app.retrieve import hyde as hyde_module
from app.retrieve import retrieve as retrieve_module
from app.retrieve.hyde import HYDE_MAX_QUERY_WORDS, generate_hypothetical_answer, should_use_hyde
from app.retrieve.retrieve import retrieve


def _interaction_with_text(text: str) -> dict:
    return {"steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]}


# --- generate_hypothetical_answer (unit) ---------------------------------------


@pytest.mark.asyncio
async def test_generates_a_hypothetical_passage(monkeypatch):
    async def fake_run_interaction(*, system_instruction, input_data):
        assert input_data == "how does raft handle quorum loss?"
        return _interaction_with_text(
            "Raft requires a majority of nodes to remain available; losing "
            "quorum halts new commits until it's restored."
        )

    monkeypatch.setattr(hyde_module.generate_module, "run_interaction", fake_run_interaction)

    result = await generate_hypothetical_answer(query="how does raft handle quorum loss?")

    assert result is not None
    assert "quorum" in result.lower()


@pytest.mark.asyncio
async def test_falls_back_to_none_on_generate_error(monkeypatch):
    async def fake_run_interaction(**kwargs):
        raise GenerateError("generate_call_failed", "upstream boom")

    monkeypatch.setattr(hyde_module.generate_module, "run_interaction", fake_run_interaction)

    result = await generate_hypothetical_answer(query="anything")

    assert result is None


@pytest.mark.asyncio
async def test_falls_back_to_none_on_unexpected_exception(monkeypatch):
    async def fake_run_interaction(**kwargs):
        raise RuntimeError("something else entirely broke")

    monkeypatch.setattr(hyde_module.generate_module, "run_interaction", fake_run_interaction)

    result = await generate_hypothetical_answer(query="anything")

    assert result is None


@pytest.mark.asyncio
async def test_falls_back_to_none_on_empty_output(monkeypatch):
    async def fake_run_interaction(**kwargs):
        return _interaction_with_text("")

    monkeypatch.setattr(hyde_module.generate_module, "run_interaction", fake_run_interaction)

    result = await generate_hypothetical_answer(query="anything")

    assert result is None


# --- retrieve() wiring ----------------------------------------------------------


class _CapturingEmbedClient:
    provider = "jina"

    def __init__(self):
        self.calls: list[dict] = []

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        self.calls.append({"text": text, "task": task})
        return [0.1] * 1024

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
        raise NotImplementedError


class _CapturingRerankClient:
    def __init__(self):
        self.last_query: str | None = None

    async def rerank(self, *, query, documents, top_n):
        self.last_query = query
        return []


class _CapturingRetrieveStorage:
    def __init__(self):
        self.last_fts_query_text: str | None = None

    async def vector_search(self, *, user_jwt, query_embedding, match_count, primary_provider):
        return []

    async def fts_search(self, *, user_jwt, query_text, match_count):
        self.last_fts_query_text = query_text
        return []


@pytest.fixture(autouse=True)
def _reset():
    yield
    embed_module.set_embed_client(embed_module.JinaEmbedClient())
    retrieve_module.set_rerank_client(retrieve_module.CohereRerankClient())
    retrieve_module.set_retrieve_storage(retrieve_module.SupabaseRetrieveStorage())


@pytest.mark.asyncio
async def test_use_hyde_embeds_the_hypothetical_as_a_passage_not_the_query(monkeypatch):
    async def fake_run_interaction(*, system_instruction, input_data):
        return _interaction_with_text("Raft elects a single leader to replicate its log.")

    monkeypatch.setattr(hyde_module.generate_module, "run_interaction", fake_run_interaction)

    embed_client = _CapturingEmbedClient()
    rerank = _CapturingRerankClient()
    storage = _CapturingRetrieveStorage()
    embed_module.set_embed_client(embed_client)
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    await retrieve(user_jwt="t", query="how does raft work?", use_hyde=True)

    assert len(embed_client.calls) == 1
    assert embed_client.calls[0]["text"] == "Raft elects a single leader to replicate its log."
    assert embed_client.calls[0]["task"] == "retrieval.passage"
    # FTS still sees the real query, not the hypothetical.
    assert storage.last_fts_query_text == "how does raft work?"


@pytest.mark.asyncio
async def test_use_hyde_false_by_default_is_unchanged_from_pre_5_2_shape(monkeypatch):
    called = False

    async def fake_run_interaction(**kwargs):
        nonlocal called
        called = True
        return _interaction_with_text("should never be called")

    monkeypatch.setattr(hyde_module.generate_module, "run_interaction", fake_run_interaction)

    embed_client = _CapturingEmbedClient()
    embed_module.set_embed_client(embed_client)
    retrieve_module.set_retrieve_storage(_CapturingRetrieveStorage())

    await retrieve(user_jwt="t", query="how does raft work?")

    assert called is False
    assert embed_client.calls == [{"text": "how does raft work?", "task": "retrieval.query"}]


@pytest.mark.asyncio
async def test_use_hyde_falls_back_to_real_query_when_generation_fails(monkeypatch):
    async def fake_run_interaction(**kwargs):
        raise GenerateError("generate_call_failed", "upstream boom")

    monkeypatch.setattr(hyde_module.generate_module, "run_interaction", fake_run_interaction)

    embed_client = _CapturingEmbedClient()
    embed_module.set_embed_client(embed_client)
    retrieve_module.set_retrieve_storage(_CapturingRetrieveStorage())

    await retrieve(user_jwt="t", query="how does raft work?", use_hyde=True)

    assert embed_client.calls == [{"text": "how does raft work?", "task": "retrieval.query"}]


# --- Stage 1.5's own fixture, re-run with HyDE enabled (this stage's own exit criteria) --


class _ScoredRerankClient:
    def __init__(self, scores_by_content: dict[str, float]):
        self.scores_by_content = scores_by_content

    async def rerank(self, *, query, documents, top_n):
        scored = [(i, self.scores_by_content.get(doc, 0.0)) for i, doc in enumerate(documents)]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_n]


def _chunk(chunk_id, content):
    return {"id": chunk_id, "document_id": f"doc-for-{chunk_id}", "ordinal": 0, "content": content, "meta": {}}


@pytest.mark.asyncio
async def test_known_relevant_chunk_still_in_top_3_with_hyde_enabled(monkeypatch):
    async def fake_run_interaction(*, system_instruction, input_data):
        return _interaction_with_text("Sealed files stay searchable by metadata only.")

    monkeypatch.setattr(hyde_module.generate_module, "run_interaction", fake_run_interaction)

    relevant = _chunk("relevant-1", "Cerebro seals files behind a passphrase")
    distractors = [
        _chunk("noise-1", "Bananas are a good source of potassium"),
        _chunk("noise-2", "The weather in Tokyo is mild in spring"),
    ]
    all_chunks = [relevant, *distractors]
    storage = _CapturingRetrieveStorage()
    storage.vector_search = lambda **kwargs: _async_return(all_chunks)  # type: ignore[method-assign]
    rerank = _ScoredRerankClient(
        scores_by_content={relevant["content"]: 0.95, **{c["content"]: 0.1 for c in distractors}}
    )

    embed_module.set_embed_client(_CapturingEmbedClient())
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(user_jwt="t", query="how do sealed files work", use_hyde=True)

    top_3_ids = [r.chunk_id for r in results[:3]]
    assert "relevant-1" in top_3_ids
    assert results[0].chunk_id == "relevant-1"


async def _async_return(value):
    return value


# --- HyDE recovering a result direct retrieval alone misses ---------------------


class _KeyedEmbedClient:
    """Returns a distinct marker vector per exact input text, so a fake
    vector store can simulate "this text's embedding is semantically
    close to this chunk" without a real model — the same style Stage
    1.5's own tests use (a controlled fake, not a real embedding
    space)."""

    provider = "jina"

    def __init__(self, vectors_by_text: dict[str, list[float]]):
        self._vectors_by_text = vectors_by_text

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        return self._vectors_by_text[text]

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
        raise NotImplementedError


class _SemanticVectorStorage:
    """vector_search returns whichever chunk set was registered against
    the exact embedding vector it receives — the fake's way of modeling
    "direct query embedding overlaps only the noise; the hypothetical
    answer's embedding overlaps the real relevant chunk."""

    def __init__(self, results_by_vector: dict[tuple[float, ...], list[dict]]):
        self._results_by_vector = results_by_vector

    async def vector_search(self, *, user_jwt, query_embedding, match_count, primary_provider):
        return self._results_by_vector.get(tuple(query_embedding), [])[:match_count]

    async def fts_search(self, *, user_jwt, query_text, match_count):
        return []


@pytest.mark.asyncio
async def test_hyde_recovers_a_result_direct_retrieval_alone_misses(monkeypatch):
    raw_query = "what about quorum loss?"
    hypothetical = "Raft requires a live majority; losing quorum halts new commits."
    relevant = _chunk("relevant-1", "Raft halts commits without a majority of live nodes")
    noise = [_chunk("noise-1", "unrelated content")]

    raw_vector = [1.0] + [0.0] * 1023
    hyde_vector = [0.0, 1.0] + [0.0] * 1022

    async def fake_run_interaction(*, system_instruction, input_data):
        return _interaction_with_text(hypothetical)

    monkeypatch.setattr(hyde_module.generate_module, "run_interaction", fake_run_interaction)

    embed_client = _KeyedEmbedClient({raw_query: raw_vector, hypothetical: hyde_vector})
    storage = _SemanticVectorStorage(
        {tuple(raw_vector): noise, tuple(hyde_vector): [relevant, *noise]}
    )
    rerank = _ScoredRerankClient(
        scores_by_content={relevant["content"]: 0.95, "unrelated content": 0.1}
    )
    embed_module.set_embed_client(embed_client)
    retrieve_module.set_rerank_client(rerank)
    retrieve_module.set_retrieve_storage(storage)

    direct_results = await retrieve(user_jwt="t", query=raw_query)
    hyde_results = await retrieve(user_jwt="t", query=raw_query, use_hyde=True)

    assert "relevant-1" not in [r.chunk_id for r in direct_results]
    assert "relevant-1" in [r.chunk_id for r in hyde_results]


# --- should_use_hyde (Stage 7.9 — conditional HyDE) --------------------------


def test_short_query_uses_hyde():
    assert should_use_hyde("what's in the schedule") is True


def test_long_detailed_query_skips_hyde():
    long_query = (
        "how does the sealed-document unlock flow derive the passphrase-based "
        "key client-side and verify it against the stored claim server-side"
    )
    assert len(long_query.split()) > HYDE_MAX_QUERY_WORDS
    assert should_use_hyde(long_query) is False


def test_query_at_exactly_the_word_limit_still_uses_hyde():
    query = " ".join(["word"] * HYDE_MAX_QUERY_WORDS)
    assert should_use_hyde(query) is True


def test_query_one_word_over_the_limit_skips_hyde():
    query = " ".join(["word"] * (HYDE_MAX_QUERY_WORDS + 1))
    assert should_use_hyde(query) is False
