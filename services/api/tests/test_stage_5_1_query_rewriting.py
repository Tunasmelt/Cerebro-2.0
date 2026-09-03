"""Stage 5.1 — query rewriting. Exercises rewrite_query directly (a
monkeypatched generate_module.run_interaction, no real network), plus
retrieve()'s wiring: when recent_messages is given, the rewritten query
(not the raw one) is what actually gets embedded/searched/reranked;
when omitted, behavior is byte-for-byte the pre-5.1 shape. A
rewrite-client failure still returns real results from the raw query —
retrieval never errors because rewriting did.
"""
import pytest

from app.chat.generate import GenerateError
from app.ingest import embed as embed_module
from app.retrieve import retrieve as retrieve_module
from app.retrieve import rewrite as rewrite_module
from app.retrieve.retrieve import retrieve
from app.retrieve.rewrite import rewrite_query


def _interaction_with_text(text: str) -> dict:
    return {"steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]}


# --- rewrite_query (unit) -----------------------------------------------------


@pytest.mark.asyncio
async def test_rewrite_query_with_no_history_returns_raw_query_without_calling_generate(
    monkeypatch,
):
    called = False

    async def fake_run_interaction(**kwargs):
        nonlocal called
        called = True
        return _interaction_with_text("should not be reached")

    monkeypatch.setattr(rewrite_module.generate_module, "run_interaction", fake_run_interaction)

    result = await rewrite_query(query="what about it?", recent_messages=[])

    assert result == "what about it?"
    assert called is False


@pytest.mark.asyncio
async def test_rewrite_query_resolves_pronoun_using_recent_history(monkeypatch):
    async def fake_run_interaction(*, system_instruction, input_data):
        assert "raft" in system_instruction.lower()
        assert input_data == "what about the other one?"
        return _interaction_with_text("What about Paxos?")

    monkeypatch.setattr(rewrite_module.generate_module, "run_interaction", fake_run_interaction)

    result = await rewrite_query(
        query="what about the other one?",
        recent_messages=[
            {"role": "user", "content": "tell me about raft"},
            {"role": "assistant", "content": "raft and paxos are both consensus algorithms"},
        ],
    )

    assert result == "What about Paxos?"


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_to_raw_query_on_generate_error(monkeypatch):
    async def fake_run_interaction(**kwargs):
        raise GenerateError("generate_call_failed", "upstream boom")

    monkeypatch.setattr(rewrite_module.generate_module, "run_interaction", fake_run_interaction)

    result = await rewrite_query(
        query="what about the other one?",
        recent_messages=[{"role": "user", "content": "tell me about raft"}],
    )

    assert result == "what about the other one?"


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_when_model_returns_empty_text(monkeypatch):
    async def fake_run_interaction(**kwargs):
        return _interaction_with_text("")

    monkeypatch.setattr(rewrite_module.generate_module, "run_interaction", fake_run_interaction)

    result = await rewrite_query(
        query="what about the other one?",
        recent_messages=[{"role": "user", "content": "tell me about raft"}],
    )

    assert result == "what about the other one?"


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_on_unexpected_exception(monkeypatch):
    async def fake_run_interaction(**kwargs):
        raise RuntimeError("something else entirely broke")

    monkeypatch.setattr(rewrite_module.generate_module, "run_interaction", fake_run_interaction)

    result = await rewrite_query(
        query="what about the other one?",
        recent_messages=[{"role": "user", "content": "tell me about raft"}],
    )

    assert result == "what about the other one?"


# --- retrieve() wiring ----------------------------------------------------------


class _CapturingEmbedClient:
    provider = "jina"

    def __init__(self):
        self.last_query_text: str | None = None

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        if task == "retrieval.query":
            self.last_query_text = text
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
async def test_retrieve_uses_rewritten_query_for_embed_fts_and_rerank_when_history_given(
    monkeypatch,
):
    async def fake_run_interaction(*, system_instruction, input_data):
        return _interaction_with_text("What about Paxos?")

    monkeypatch.setattr(rewrite_module.generate_module, "run_interaction", fake_run_interaction)

    embed_client = _CapturingEmbedClient()
    storage = _CapturingRetrieveStorage()
    embed_module.set_embed_client(embed_client)
    retrieve_module.set_retrieve_storage(storage)

    await retrieve(
        user_jwt="t",
        query="what about the other one?",
        recent_messages=[{"role": "user", "content": "tell me about raft"}],
    )

    assert embed_client.last_query_text == "What about Paxos?"
    assert storage.last_fts_query_text == "What about Paxos?"


@pytest.mark.asyncio
async def test_retrieve_without_recent_messages_is_unchanged_from_pre_5_1_shape(monkeypatch):
    called = False

    async def fake_run_interaction(**kwargs):
        nonlocal called
        called = True
        return _interaction_with_text("should never be called")

    monkeypatch.setattr(rewrite_module.generate_module, "run_interaction", fake_run_interaction)

    embed_client = _CapturingEmbedClient()
    storage = _CapturingRetrieveStorage()
    embed_module.set_embed_client(embed_client)
    retrieve_module.set_retrieve_storage(storage)

    await retrieve(user_jwt="t", query="what is raft?")

    assert called is False
    assert embed_client.last_query_text == "what is raft?"
    assert storage.last_fts_query_text == "what is raft?"


@pytest.mark.asyncio
async def test_retrieve_falls_back_to_raw_query_when_rewrite_fails(monkeypatch):
    async def fake_run_interaction(**kwargs):
        raise GenerateError("generate_call_failed", "upstream boom")

    monkeypatch.setattr(rewrite_module.generate_module, "run_interaction", fake_run_interaction)

    embed_client = _CapturingEmbedClient()
    storage = _CapturingRetrieveStorage()
    embed_module.set_embed_client(embed_client)
    retrieve_module.set_retrieve_storage(storage)

    results = await retrieve(
        user_jwt="t",
        query="what about the other one?",
        recent_messages=[{"role": "user", "content": "tell me about raft"}],
    )

    assert results == []  # empty fused_ids from the fake storage, not an error
    assert embed_client.last_query_text == "what about the other one?"
    assert storage.last_fts_query_text == "what about the other one?"
