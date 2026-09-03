"""Stage 5.3 — proves chat/stream.py actually calls
reinforce_co_retrieval with the turn's real final chunk set after
retrieval, and that a failure in reinforcement never breaks the chat
turn itself (still reaches `done`) — same best-effort posture as any
other optional quality improvement in this codebase.
"""
import json

import pytest

from app.chat import generate as generate_module
from app.chat import storage as chat_storage_module
from app.chat import stream as stream_module
from app.chat.generate import GeminiGenerateClient, set_generate_client
from app.graph import edges as edges_module
from app.ingest import embed as embed_module
from app.retrieve import retrieve as retrieve_module


class _FakeEmbedClient:
    provider = "jina"

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        return [0.1] * 1024

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
        raise NotImplementedError


class _FakeRerankClient:
    async def rerank(self, *, query, documents, top_n):
        return [(i, 0.9) for i in range(len(documents))][:top_n]


class _FakeRetrieveStorage:
    def __init__(self, *, chunks):
        self.chunks = chunks

    async def vector_search(self, *, user_jwt, query_embedding, match_count, primary_provider):
        return self.chunks[:match_count]

    async def fts_search(self, *, user_jwt, query_text, match_count):
        return self.chunks[:match_count]


class _FakeGenerateClient:
    async def stream_text(self, *, system_instruction, input_text):
        yield "hi"


class _FakeChatStorage:
    async def save_message(self, **kwargs):
        pass


class _FakeChunkEdgesStorage:
    def __init__(self, *, raise_error: bool = False):
        self.raise_error = raise_error
        self.reinforce_calls: list[dict] = []

    async def reinforce_co_retrieval(self, *, user_jwt, user_id, chunk_ids):
        self.reinforce_calls.append({"user_jwt": user_jwt, "user_id": user_id, "chunk_ids": chunk_ids})
        if self.raise_error:
            raise RuntimeError("simulated edge-store failure")

    async def create_explicit_link(self, **kwargs):
        raise NotImplementedError

    async def list_edges_for_chunks(self, **kwargs):
        raise NotImplementedError


def _chunk(chunk_id, content, document_id=None):
    return {
        "id": chunk_id,
        "document_id": document_id or f"doc-for-{chunk_id}",
        "ordinal": 0,
        "content": content,
        "meta": {},
    }


async def _no_op_run_interaction(**kwargs):
    # retrieve() now runs HyDE unconditionally (chat/stream.py passes
    # use_hyde=True) — without this stub every test here would fire a
    # real network call to Gemini via retrieve/hyde.py's run_interaction.
    return {"steps": []}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(generate_module, "run_interaction", _no_op_run_interaction)
    yield
    embed_module.set_embed_client(embed_module.JinaEmbedClient())
    retrieve_module.set_rerank_client(retrieve_module.CohereRerankClient())
    retrieve_module.set_retrieve_storage(retrieve_module.SupabaseRetrieveStorage())
    set_generate_client(GeminiGenerateClient())
    chat_storage_module.set_chat_storage(chat_storage_module.SupabaseChatStorage())
    edges_module.set_chunk_edges_storage(edges_module.SupabaseChunkEdgesStorage())


async def _collect_events(agen):
    events = []
    async for raw in agen:
        lines = raw.strip().split("\n")
        event_name = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        events.append((event_name, data))
    return events


@pytest.mark.asyncio
async def test_stream_chat_reinforces_the_turns_real_final_chunk_set():
    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(_FakeRerankClient())
    retrieve_module.set_retrieve_storage(
        _FakeRetrieveStorage(
            chunks=[
                _chunk("c1111111-1111-1111-1111-111111111111", "a"),
                _chunk("c2222222-2222-2222-2222-222222222222", "b"),
            ]
        )
    )
    set_generate_client(_FakeGenerateClient())
    chat_storage_module.set_chat_storage(_FakeChatStorage())
    fake_edges = _FakeChunkEdgesStorage()
    edges_module.set_chunk_edges_storage(fake_edges)

    await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="what is X?"
        )
    )

    assert len(fake_edges.reinforce_calls) == 1
    call = fake_edges.reinforce_calls[0]
    assert call["user_id"] == "u1"
    assert set(call["chunk_ids"]) == {
        "c1111111-1111-1111-1111-111111111111",
        "c2222222-2222-2222-2222-222222222222",
    }


@pytest.mark.asyncio
async def test_reinforcement_failure_never_breaks_the_chat_turn():
    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(_FakeRerankClient())
    retrieve_module.set_retrieve_storage(
        _FakeRetrieveStorage(chunks=[_chunk("c1111111-1111-1111-1111-111111111111", "a")])
    )
    set_generate_client(_FakeGenerateClient())
    chat_storage_module.set_chat_storage(_FakeChatStorage())
    edges_module.set_chunk_edges_storage(_FakeChunkEdgesStorage(raise_error=True))

    events = await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="what is X?"
        )
    )

    event_names = [name for name, _ in events]
    assert "error" not in event_names
    assert event_names[-1] == "done"
