"""Stage 1.7 — chat & SSE.

Exit criteria: SSE stream emits `retrieval` (real chunk/document IDs)
before any `token` event, then tokens, then `citation` events, then
`done`.

Tests:
- Automated: assert `retrieval` event timestamp precedes first `token`
  event timestamp on every run, not just typically.
- Citation chips in a response resolve to real chunks — no citation
  pointing at a chunk ID that wasn't actually retrieved.

Uses fake embed/rerank/retrieve-storage clients (same pattern as
test_stage_1_5_retrieve.py) plus a fake generate client and fake chat
storage, so the whole stream is deterministic and network-free.
"""
import json

import pytest

from app.chat import storage as chat_storage_module
from app.chat import stream as stream_module
from app.chat.generate import GeminiGenerateClient, parse_sse_line, set_generate_client
from app.chat.prompt import build_system_instruction, extract_citations
from app.ingest import embed as embed_module
from app.retrieve import retrieve as retrieve_module
from app.retrieve.retrieve import RetrievedChunk


class _FakeEmbedClient:
    provider = "jina"

    async def embed_text(self, text: str) -> list[float]:
        return [0.1] * 1024

    async def embed_image(self, image_bytes: bytes) -> list[float]:
        raise NotImplementedError


class _FakeRerankClient:
    async def rerank(self, *, query, documents, top_n):
        # Everything relevant, in original order — this file isn't
        # testing rerank quality, just the SSE contract around it.
        return [(i, 0.9) for i in range(len(documents))][:top_n]


class _FakeRetrieveStorage:
    def __init__(self, *, vector_results, fts_results):
        self.vector_results = vector_results
        self.fts_results = fts_results

    async def vector_search(self, *, user_jwt, query_embedding, match_count, primary_provider):
        return self.vector_results[:match_count]

    async def fts_search(self, *, user_jwt, query_text, match_count):
        return self.fts_results[:match_count]


class _FakeGenerateClient:
    def __init__(self, text_chunks: list[str]):
        self.text_chunks = text_chunks
        self.calls: list[dict] = []

    async def stream_text(self, *, system_instruction, input_text):
        self.calls.append({"system_instruction": system_instruction, "input_text": input_text})
        for chunk in self.text_chunks:
            yield chunk


class _FakeChatStorage:
    def __init__(self):
        self.messages: list[dict] = []

    async def create_session(self, *, user_jwt, user_id):
        return "session-1"

    async def get_session(self, *, user_jwt, session_id):
        return {"id": session_id}

    async def save_message(
        self,
        *,
        user_jwt,
        session_id,
        user_id,
        role,
        content,
        retrieved_chunk_ids,
        trace_id=None,
    ):
        self.messages.append(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "retrieved_chunk_ids": retrieved_chunk_ids,
                "trace_id": trace_id,
            }
        )


def _chunk(chunk_id, content, document_id=None):
    return {
        "id": chunk_id,
        "document_id": document_id or f"doc-for-{chunk_id}",
        "ordinal": 0,
        "content": content,
        "meta": {},
    }


@pytest.fixture(autouse=True)
def _reset():
    yield
    embed_module.set_embed_client(embed_module.JinaEmbedClient())
    retrieve_module.set_rerank_client(retrieve_module.CohereRerankClient())
    retrieve_module.set_retrieve_storage(retrieve_module.SupabaseRetrieveStorage())
    set_generate_client(GeminiGenerateClient())
    chat_storage_module.set_chat_storage(chat_storage_module.SupabaseChatStorage())


def _wire_retrieve(chunks: list[dict]):
    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(_FakeRerankClient())
    retrieve_module.set_retrieve_storage(
        _FakeRetrieveStorage(vector_results=chunks, fts_results=chunks)
    )


async def _collect_events(agen):
    events = []
    async for raw in agen:
        # raw is "event: X\ndata: {...}\n\n"
        lines = raw.strip().split("\n")
        event_name = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        events.append((event_name, data))
    return events


# --- ordering: retrieval before any token, every run --------------------------


@pytest.mark.asyncio
async def test_retrieval_event_precedes_first_token_event():
    _wire_retrieve([_chunk("c1111111-1111-1111-1111-111111111111", "relevant content")])
    set_generate_client(_FakeGenerateClient(["hello ", "world"]))
    chat_storage = _FakeChatStorage()
    chat_storage_module.set_chat_storage(chat_storage)

    events = await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="what is X?"
        )
    )

    event_names = [name for name, _ in events]
    first_token_index = event_names.index("token")
    retrieval_index = event_names.index("retrieval")
    assert retrieval_index < first_token_index
    assert event_names[0] == "retrieval"  # nothing at all comes before it


@pytest.mark.asyncio
async def test_full_event_sequence_order_retrieval_tokens_citations_done():
    _wire_retrieve([_chunk("c1111111-1111-1111-1111-111111111111", "relevant content", document_id="d1111111-1111-1111-1111-111111111111")])
    set_generate_client(
        _FakeGenerateClient(["The answer is X ", "[[chunk:c1111111-1111-1111-1111-111111111111]]."])
    )
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    events = await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="what is X?"
        )
    )

    event_names = [name for name, _ in events]
    assert event_names == ["retrieval", "token", "token", "citation", "done"]
    assert events[-2][1] == {"chunk_id": "c1111111-1111-1111-1111-111111111111", "document_id": "d1111111-1111-1111-1111-111111111111"}


# --- citations must resolve to real retrieved chunks ---------------------------


@pytest.mark.asyncio
async def test_hallucinated_citation_is_dropped_not_forwarded():
    _wire_retrieve([_chunk("c1111111-1111-1111-1111-111111111111", "relevant content", document_id="d1111111-1111-1111-1111-111111111111")])
    # Model cites a chunk id that was never retrieved.
    set_generate_client(
        _FakeGenerateClient(["Per [[chunk:c1111111-1111-1111-1111-111111111111]] and also [[chunk:00000000-0000-0000-0000-000000000000]]."])
    )
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    events = await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="q"
        )
    )

    citations = [data for name, data in events if name == "citation"]
    assert citations == [{"chunk_id": "c1111111-1111-1111-1111-111111111111", "document_id": "d1111111-1111-1111-1111-111111111111"}]


@pytest.mark.asyncio
async def test_duplicate_citation_markers_only_emit_once():
    _wire_retrieve([_chunk("c1111111-1111-1111-1111-111111111111", "relevant content", document_id="d1111111-1111-1111-1111-111111111111")])
    set_generate_client(
        _FakeGenerateClient(["[[chunk:c1111111-1111-1111-1111-111111111111]] and again [[chunk:c1111111-1111-1111-1111-111111111111]]."])
    )
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    events = await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="q"
        )
    )

    citations = [data for name, data in events if name == "citation"]
    assert citations == [{"chunk_id": "c1111111-1111-1111-1111-111111111111", "document_id": "d1111111-1111-1111-1111-111111111111"}]


@pytest.mark.asyncio
async def test_no_relevant_content_still_emits_retrieval_before_done():
    _wire_retrieve([])
    set_generate_client(_FakeGenerateClient(["I don't know."]))
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    events = await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="q"
        )
    )

    assert events[0] == ("retrieval", {"chunk_ids": [], "document_ids": []})
    assert events[-1][0] == "done"


# --- persistence: real retrieved_chunk_ids stored on the assistant message -----


@pytest.mark.asyncio
async def test_assistant_message_persists_real_retrieved_chunk_ids():
    _wire_retrieve([_chunk("c1111111-1111-1111-1111-111111111111", "relevant content", document_id="d1111111-1111-1111-1111-111111111111")])
    set_generate_client(_FakeGenerateClient(["answer [[chunk:c1111111-1111-1111-1111-111111111111]]"]))
    chat_storage = _FakeChatStorage()
    chat_storage_module.set_chat_storage(chat_storage)

    await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="q"
        )
    )

    assistant_messages = [m for m in chat_storage.messages if m["role"] == "assistant"]
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["retrieved_chunk_ids"] == ["c1111111-1111-1111-1111-111111111111"]
    user_messages = [m for m in chat_storage.messages if m["role"] == "user"]
    assert len(user_messages) == 1
    assert user_messages[0]["content"] == "q"


# --- prompt.py unit tests -------------------------------------------------------


def test_build_system_instruction_includes_chunk_markers_and_content():
    chunks = [
        RetrievedChunk(
            chunk_id="c1111111-1111-1111-1111-111111111111",
            document_id="d1111111-1111-1111-1111-111111111111",
            ordinal=0,
            content="Paris is the capital of France.",
            meta={},
            relevance_score=0.9,
        )
    ]
    instruction = build_system_instruction(chunks)
    assert "[[chunk:c1111111-1111-1111-1111-111111111111]]" in instruction
    assert "Paris is the capital of France." in instruction


def test_build_system_instruction_handles_empty_context():
    instruction = build_system_instruction([])
    assert "No relevant context" in instruction


# --- generate.py's SSE line parsing (regression: real streaming call --------
# --- surfaced a `[DONE]` terminator line that isn't JSON, and would ----------
# --- crash json.loads on every real request if not special-cased) -----------


def test_parse_sse_line_extracts_text_delta():
    line = 'data: {"index":1,"delta":{"text":"hello","type":"text"},"event_type":"step.delta"}'
    assert parse_sse_line(line) == "hello"


def test_parse_sse_line_ignores_non_text_deltas():
    line = 'data: {"index":0,"delta":{"type":"thought_signature"},"event_type":"step.delta"}'
    assert parse_sse_line(line) is None


def test_parse_sse_line_ignores_non_delta_events():
    line = 'data: {"event_type":"interaction.created","interaction":{}}'
    assert parse_sse_line(line) is None


def test_parse_sse_line_handles_done_terminator_without_crashing():
    # Confirmed against a real streaming call: the final line is a
    # literal `[DONE]`, not JSON. json.loads would raise here otherwise.
    assert parse_sse_line("data: [DONE]") is None


def test_parse_sse_line_ignores_non_data_lines():
    assert parse_sse_line("event: step.delta") is None
    assert parse_sse_line("") is None


def test_extract_citations_filters_unknown_ids():
    chunks = [
        RetrievedChunk(
            chunk_id="c1111111-1111-1111-1111-111111111111",
            document_id="d1111111-1111-1111-1111-111111111111",
            ordinal=0,
            content="x",
            meta={},
            relevance_score=0.9,
        )
    ]
    text = "See [[chunk:c1111111-1111-1111-1111-111111111111]] and [[chunk:00000000-0000-0000-0000-000000000000]]."
    citations = extract_citations(text, chunks)
    assert [c.chunk_id for c in citations] == ["c1111111-1111-1111-1111-111111111111"]
