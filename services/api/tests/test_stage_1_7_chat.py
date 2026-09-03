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
import asyncio
import json

import pytest

from app.chat import generate as generate_module
from app.chat import storage as chat_storage_module
from app.chat import stream as stream_module
from app.chat.generate import GeminiGenerateClient, parse_sse_line, set_generate_client
from app.chat.prompt import build_system_instruction, extract_citations
from app.core import documents_storage as documents_storage_module
from app.ingest import embed as embed_module
from app.retrieve import retrieve as retrieve_module
from app.retrieve.retrieve import RetrievedChunk


class _FakeEmbedClient:
    provider = "jina"

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        return [0.1] * 1024

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
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
    def __init__(self, text_chunks: list[str], *, fail_after: int | None = None):
        self.text_chunks = text_chunks
        self.calls: list[dict] = []
        self.fail_after = fail_after  # raise after yielding this many chunks

    async def stream_text(self, *, system_instruction, input_text):
        self.calls.append({"system_instruction": system_instruction, "input_text": input_text})
        for i, chunk in enumerate(self.text_chunks):
            if self.fail_after is not None and i >= self.fail_after:
                raise TimeoutError("simulated network timeout")
            yield chunk


class _FakeChatStorage:
    def __init__(self):
        self.messages: list[dict] = []
        self.recent_messages_to_return: list[dict] = []

    async def create_session(self, *, user_jwt, user_id):
        return "session-1"

    async def get_session(self, *, user_jwt, session_id):
        return {"id": session_id}

    async def get_recent_messages(self, *, user_jwt, session_id, limit):
        return self.recent_messages_to_return

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


async def _no_op_run_interaction(**kwargs):
    # Retrieval quality pass — retrieve() now runs HyDE unconditionally
    # (chat/stream.py passes use_hyde=True), which calls this same
    # run_interaction under the hood (retrieve/hyde.py). Without a stub,
    # every test in this file would fire a real network call to Gemini —
    # this file's own docstring promises "deterministic and network-free".
    # Empty output makes generate_hypothetical_answer fall back to None,
    # identical to how these tests behaved before HyDE existed.
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
    documents_storage_module.set_documents_storage(
        documents_storage_module.SupabaseDocumentsStorage()
    )


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


# --- Stage 7.9: HyDE is conditional on query shape, not unconditional --------


@pytest.mark.asyncio
async def test_short_query_is_passed_to_retrieve_with_hyde_enabled(monkeypatch):
    calls: list[dict] = []

    async def fake_retrieve(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(stream_module, "retrieve", fake_retrieve)
    set_generate_client(_FakeGenerateClient(["ok"]))
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="what's in the schedule"
        )
    )

    assert calls[0]["use_hyde"] is True


@pytest.mark.asyncio
async def test_long_detailed_query_is_passed_to_retrieve_with_hyde_disabled(monkeypatch):
    calls: list[dict] = []

    async def fake_retrieve(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(stream_module, "retrieve", fake_retrieve)
    set_generate_client(_FakeGenerateClient(["ok"]))
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    long_query = (
        "how does the sealed-document unlock flow derive the passphrase-based "
        "key client-side and verify it against the stored claim server-side"
    )
    await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query=long_query
        )
    )

    assert calls[0]["use_hyde"] is False


# --- Stage 7.11: heartbeat events during a slow retrieval/HyDE gap -----------


@pytest.mark.asyncio
async def test_slow_retrieval_emits_at_least_one_heartbeat_before_retrieval_event(
    monkeypatch,
):
    monkeypatch.setattr(stream_module, "HEARTBEAT_INTERVAL_SECONDS", 0.01)

    async def slow_retrieve(**kwargs):
        await asyncio.sleep(0.05)  # several heartbeat intervals
        return []

    monkeypatch.setattr(stream_module, "retrieve", slow_retrieve)
    set_generate_client(_FakeGenerateClient(["ok"]))
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    events = await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="anything"
        )
    )

    event_names = [name for name, _ in events]
    retrieval_index = event_names.index("retrieval")
    # Only heartbeat events precede retrieval — never a token, never
    # anything else — and there's at least one of them.
    assert event_names[:retrieval_index] == ["heartbeat"] * retrieval_index
    assert retrieval_index >= 1


@pytest.mark.asyncio
async def test_fast_retrieval_emits_no_heartbeat_events():
    _wire_retrieve([_chunk("c1111111-1111-1111-1111-111111111111", "relevant content")])
    set_generate_client(_FakeGenerateClient(["ok"]))
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    events = await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="anything"
        )
    )

    assert "heartbeat" not in [name for name, _ in events]


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


# --- generation failures surface as a real error event, not a dead connection --
# Regression: a live production request hit httpx.ReadTimeout mid-generation;
# the exception propagated unhandled and the connection just died after
# `retrieval` with no error event and no `done` — the client had no way to
# tell "failed" from "still working". See chat/stream.py's module docstring.


@pytest.mark.asyncio
async def test_generation_failure_yields_an_error_event_not_a_dead_stream():
    _wire_retrieve([_chunk("c1111111-1111-1111-1111-111111111111", "relevant content")])
    set_generate_client(_FakeGenerateClient(["partial ", "more"], fail_after=1))
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    events = await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="q"
        )
    )

    event_names = [name for name, _ in events]
    assert event_names == ["retrieval", "token", "error"]
    assert "done" not in event_names
    assert events[-1][1]["code"] == "chat_turn_failed"


@pytest.mark.asyncio
async def test_error_message_falls_back_to_exception_type_when_str_is_empty():
    # Regression: a real production httpx.ReadTimeout has an empty
    # str(exc) (no message was ever set on it), which surfaced as
    # {"message": ""} to the client — useless for debugging. The
    # exception's type name is now used as a fallback.
    class _FakeGenerateClientEmptyError:
        async def stream_text(self, *, system_instruction, input_text):
            raise TimeoutError()
            yield  # pragma: no cover - makes this an async generator

    _wire_retrieve([_chunk("c1111111-1111-1111-1111-111111111111", "relevant content")])
    set_generate_client(_FakeGenerateClientEmptyError())
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    events = await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="q"
        )
    )

    error_event = events[-1]
    assert error_event[0] == "error"
    assert error_event[1]["message"] == "TimeoutError"


@pytest.mark.asyncio
async def test_generation_failure_does_not_persist_a_partial_assistant_message():
    _wire_retrieve([_chunk("c1111111-1111-1111-1111-111111111111", "relevant content")])
    set_generate_client(_FakeGenerateClient(["partial ", "more"], fail_after=1))
    chat_storage = _FakeChatStorage()
    chat_storage_module.set_chat_storage(chat_storage)

    await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="q"
        )
    )

    assistant_messages = [m for m in chat_storage.messages if m["role"] == "assistant"]
    assert assistant_messages == []


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


# --- retrieval quality: real document titles reach the generation prompt -----


class _FakeDocumentsStorageTitlesOnly:
    """Only implements get_titles — stream_chat's title-resolution call
    is the only DocumentsStorage method a chat turn should ever touch."""

    def __init__(self, titles: dict[str, str]):
        self._titles = titles
        self.calls: list[list[str]] = []

    async def get_titles(self, *, user_jwt, document_ids):
        self.calls.append(sorted(document_ids))
        return {did: self._titles[did] for did in document_ids if did in self._titles}


@pytest.mark.asyncio
async def test_stream_chat_labels_context_with_the_real_document_title():
    """End-to-end wiring proof: stream_chat resolves the retrieved
    chunks' real document titles and the generation call actually
    receives a prompt labeled with them — not just that
    build_system_instruction can do it in isolation."""
    _wire_retrieve(
        [_chunk("c1111111-1111-1111-1111-111111111111", "9am meeting", document_id="d1111111-1111-1111-1111-111111111111")]
    )
    fake_docs_storage = _FakeDocumentsStorageTitlesOnly(
        {"d1111111-1111-1111-1111-111111111111": "Schedule.jpg"}
    )
    documents_storage_module.set_documents_storage(fake_docs_storage)
    generate_client = _FakeGenerateClient(["it's at 9am"])
    set_generate_client(generate_client)
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="when's the meeting?"
        )
    )

    assert fake_docs_storage.calls == [["d1111111-1111-1111-1111-111111111111"]]
    assert '### Source: "Schedule.jpg"' in generate_client.calls[0]["system_instruction"]


@pytest.mark.asyncio
async def test_stream_chat_title_lookup_failure_degrades_to_flat_prompt_not_a_failed_turn():
    """Best-effort, same posture as chunk-edge reinforcement: a broken
    title lookup must never turn into a failed chat turn."""

    class _BrokenDocumentsStorage:
        async def get_titles(self, *, user_jwt, document_ids):
            raise RuntimeError("simulated documents-table outage")

    _wire_retrieve(
        [_chunk("c1111111-1111-1111-1111-111111111111", "content")]
    )
    documents_storage_module.set_documents_storage(_BrokenDocumentsStorage())
    generate_client = _FakeGenerateClient(["answer"])
    set_generate_client(generate_client)
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    events = await _collect_events(
        stream_module.stream_chat(
            user_jwt="t", user_id="u1", session_id="session-1", query="q"
        )
    )

    assert events[-1][0] == "done"
    assert '### Source: "' not in generate_client.calls[0]["system_instruction"]


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


def test_build_system_instruction_without_titles_stays_flat_and_unlabeled():
    """No document_titles given (e.g. an older call site) — same flat,
    title-less format as before this change, not a behavior change for
    callers that haven't been updated to fetch titles."""
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
    assert '### Source: "' not in instruction


def test_build_system_instruction_groups_chunks_under_labeled_source_headers():
    """The real gap this closes: a question spanning more than one
    document got answered by a model that had no way to tell which chunk
    came from which file. Chunks from the same document must be grouped
    under one labeled header, in first-appearance (rerank) order."""
    chunks = [
        RetrievedChunk(
            chunk_id="c1111111-1111-1111-1111-111111111111",
            document_id="d1111111-1111-1111-1111-111111111111",
            ordinal=0,
            content="The schedule shows a 9am meeting.",
            meta={},
            relevance_score=0.95,
        ),
        RetrievedChunk(
            chunk_id="c2222222-2222-2222-2222-222222222222",
            document_id="d2222222-2222-2222-2222-222222222222",
            ordinal=0,
            content="The QA plan requires two reviewers.",
            meta={},
            relevance_score=0.9,
        ),
        RetrievedChunk(
            chunk_id="c3333333-3333-3333-3333-333333333333",
            document_id="d1111111-1111-1111-1111-111111111111",
            ordinal=1,
            content="The 9am meeting is in room 4.",
            meta={},
            relevance_score=0.8,
        ),
    ]
    document_titles = {
        "d1111111-1111-1111-1111-111111111111": "Schedule.jpg",
        "d2222222-2222-2222-2222-222222222222": "QA Engineer.pdf",
    }
    instruction = build_system_instruction(chunks, document_titles)

    assert '### Source: "Schedule.jpg"' in instruction
    assert '### Source: "QA Engineer.pdf"' in instruction
    # The first document's two chunks land in one contiguous group, not
    # interleaved with the other document's chunk between them.
    schedule_section = instruction.split('### Source: "Schedule.jpg"')[1].split(
        '### Source: "QA Engineer.pdf"'
    )[0]
    assert "9am meeting" in schedule_section
    assert "room 4" in schedule_section
    assert "QA plan" not in schedule_section
    # Highest-relevance document's section comes first.
    assert instruction.index('### Source: "Schedule.jpg"') < instruction.index(
        '### Source: "QA Engineer.pdf"'
    )


def test_build_system_instruction_falls_back_to_untitled_for_an_unresolved_document():
    """document_titles is non-empty (title resolution partially
    succeeded) but doesn't cover this particular document_id — still
    labeled, just with the fallback name, rather than silently dropping
    back to the untitled flat format for the whole prompt."""
    chunks = [
        RetrievedChunk(
            chunk_id="c1111111-1111-1111-1111-111111111111",
            document_id="d1111111-1111-1111-1111-111111111111",
            ordinal=0,
            content="content",
            meta={},
            relevance_score=0.9,
        )
    ]
    instruction = build_system_instruction(
        chunks, {"d-some-other-doc": "Other Document.pdf"}
    )
    assert '### Source: "Untitled document"' in instruction


def test_build_system_instruction_empty_titles_dict_degrades_to_flat_format():
    """An empty dict (title resolution ran but returned nothing — e.g.
    every referenced document was deleted mid-request) degrades exactly
    like no titles were ever attempted, not a half-labeled prompt."""
    chunks = [
        RetrievedChunk(
            chunk_id="c1111111-1111-1111-1111-111111111111",
            document_id="d1111111-1111-1111-1111-111111111111",
            ordinal=0,
            content="content",
            meta={},
            relevance_score=0.9,
        )
    ]
    instruction = build_system_instruction(chunks, {})
    assert '### Source: "' not in instruction


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


def test_extract_citations_matches_a_sealed_document_style_chunk_id():
    """Regression: retrieve.py's _sealed_exact_matches mints chunk ids
    shaped "<document_id>:<ordinal>" for sealed content, not a bare
    36-char UUID like every other chunk. The old regex only matched the
    UUID shape, so a citation for sealed content could never actually
    match and was always silently dropped — never a client-visible bug
    report, just a citation chip that quietly never appeared."""
    document_id = "d1111111-1111-1111-1111-111111111111"
    sealed_chunk_id = f"{document_id}:3"
    chunks = [
        RetrievedChunk(
            chunk_id=sealed_chunk_id,
            document_id=document_id,
            ordinal=3,
            content="sealed content",
            meta={},
            relevance_score=1.0,
        )
    ]
    text = f"According to the sealed note [[chunk:{sealed_chunk_id}]]."
    citations = extract_citations(text, chunks)
    assert [c.chunk_id for c in citations] == [sealed_chunk_id]


# --- Stage 5.1: query rewriting wired end-to-end through stream_chat -----------


@pytest.mark.asyncio
async def test_stream_chat_rewrites_query_using_real_recent_history(monkeypatch):
    """Full plumbing: chat_storage.get_recent_messages -> stream_chat ->
    retrieve() -> rewrite_query -> the real embed client actually
    receives the rewritten text, not the raw follow-up. Proves the
    wiring, not just each piece in isolation."""
    from app.retrieve import rewrite as rewrite_module

    class _CapturingEmbedClient:
        provider = "jina"

        def __init__(self):
            self.last_query_text = None

        async def embed_text(self, text, task="retrieval.passage"):
            if task == "retrieval.query":
                self.last_query_text = text
            return [0.1] * 1024

        async def embed_image(self, image_bytes, task="retrieval.passage"):
            raise NotImplementedError

    async def fake_run_interaction(*, system_instruction, input_data):
        # retrieve() now also fires HyDE's own run_interaction call
        # (same underlying function) unconditionally — only the
        # rewrite-shaped call includes "Recent conversation" in its
        # system_instruction; HyDE's uses a different, unrelated header
        # and should just no-op here, this test's subject is rewriting.
        if "recent conversation" not in system_instruction.lower():
            return {"steps": []}
        assert "raft" in system_instruction.lower()
        return {
            "steps": [
                {"type": "model_output", "content": [{"type": "text", "text": "What about Paxos?"}]}
            ]
        }

    monkeypatch.setattr(rewrite_module.generate_module, "run_interaction", fake_run_interaction)

    embed_client = _CapturingEmbedClient()
    embed_module.set_embed_client(embed_client)
    retrieve_module.set_rerank_client(_FakeRerankClient())
    retrieve_module.set_retrieve_storage(_FakeRetrieveStorage(vector_results=[], fts_results=[]))
    set_generate_client(_FakeGenerateClient(["hi"]))
    chat_storage = _FakeChatStorage()
    chat_storage.recent_messages_to_return = [
        {"role": "user", "content": "tell me about raft"}
    ]
    chat_storage_module.set_chat_storage(chat_storage)

    await _collect_events(
        stream_module.stream_chat(
            user_jwt="t",
            user_id="u1",
            session_id="session-1",
            query="what about the other one?",
        )
    )

    assert embed_client.last_query_text == "What about Paxos?"
