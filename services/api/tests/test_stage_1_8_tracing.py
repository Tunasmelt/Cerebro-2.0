"""Stage 1.8 — observability (Langfuse tracing).

Exit criteria: Langfuse traces every turn with the full span tree.
Test: a live chat turn produces a Langfuse trace with all six expected
spans present — verified live against a real Langfuse project (Stage
1.8 conversation record: a real chat_turn trace queried back via
Langfuse's API showed all six spans — embed_query, vector_search,
fts_search, rrf_fuse, rerank, generate — each nested directly under the
root chat_turn span). This file adds a deterministic regression guard
on top of that live proof: a fake tracer records span names/order/
nesting without needing real Langfuse credentials, so a future change
that silently drops a span or breaks the nesting fails a fast CI test,
not just a manual check.

Also covers core/tracing.py's fail-open behavior — confirmed live
(same conversation record): with no Langfuse env vars set, the real SDK
degrades to a disabled client whose span context managers and
get_current_trace_id() are no-ops, never raising.
"""
import pytest

from app.chat import generate as generate_module
from app.chat import storage as chat_storage_module
from app.chat import stream as stream_module
from app.chat.generate import set_generate_client
from app.core import tracing as tracing_module
from app.ingest import embed as embed_module
from app.retrieve import retrieve as retrieve_module

EXPECTED_SPANS_IN_ORDER = [
    "embed_query",
    "vector_search",
    "fts_search",
    "rrf_fuse",
    "rerank",
    "generate",
]


class _FakeSpan:
    def __init__(self, name):
        self.name = name
        self.output = None

    def update(self, *, output=None, **kwargs):
        self.output = output


class _FakeTracer:
    """Records (span_name, parent_name) for every span opened, in the
    order they were entered — enough to assert both "all six spans
    fired" and "all five sub-spans nested under chat_turn", the same
    two things the live Langfuse query confirmed."""

    def __init__(self):
        self.opened: list[tuple[str, str | None]] = []
        self._stack: list[str] = []
        self.trace_id = "fake-trace-id-123"

    def start_as_current_observation(self, *, as_type, name, input=None, model=None):
        parent = self._stack[-1] if self._stack else None
        self.opened.append((name, parent))
        return _FakeSpanContext(self, name)

    def get_current_trace_id(self):
        return self.trace_id

    def flush(self):
        pass


class _FakeSpanContext:
    def __init__(self, tracer, name):
        self._tracer = tracer
        self._name = name

    def __enter__(self):
        self._tracer._stack.append(self._name)
        return _FakeSpan(self._name)

    def __exit__(self, *exc_info):
        self._tracer._stack.pop()
        return False


class _FakeEmbedClient:
    provider = "jina"

    async def embed_text(self, text, task: str = "retrieval.passage"):
        return [0.1] * 1024

    async def embed_image(self, image_bytes, task: str = "retrieval.passage"):
        raise NotImplementedError


class _FakeRerankClient:
    async def rerank(self, *, query, documents, top_n):
        return [(i, 0.9) for i in range(len(documents))][:top_n]


class _FakeRetrieveStorage:
    def __init__(self, chunks):
        self.chunks = chunks

    async def vector_search(self, *, user_jwt, query_embedding, match_count, primary_provider):
        return self.chunks[:match_count]

    async def fts_search(self, *, user_jwt, query_text, match_count):
        return self.chunks[:match_count]


class _FakeGenerateClient:
    model = "fake-model"

    async def stream_text(self, *, system_instruction, input_text):
        yield "answer"


class _FakeChatStorage:
    def __init__(self):
        self.messages = []

    async def create_session(self, *, user_jwt, user_id):
        return "session-1"

    async def get_session(self, *, user_jwt, session_id):
        return {"id": session_id}

    async def save_message(self, **kwargs):
        self.messages.append(kwargs)


def _chunk():
    return {
        "id": "c1111111-1111-1111-1111-111111111111",
        "document_id": "d1111111-1111-1111-1111-111111111111",
        "ordinal": 0,
        "content": "relevant content",
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
    tracing_module.set_tracer(None)
    embed_module.set_embed_client(embed_module.JinaEmbedClient())
    retrieve_module.set_rerank_client(retrieve_module.CohereRerankClient())
    retrieve_module.set_retrieve_storage(retrieve_module.SupabaseRetrieveStorage())
    from app.chat.generate import GeminiGenerateClient
    set_generate_client(GeminiGenerateClient())
    chat_storage_module.set_chat_storage(chat_storage_module.SupabaseChatStorage())


@pytest.mark.asyncio
async def test_a_chat_turn_produces_all_six_expected_spans_correctly_nested():
    fake_tracer = _FakeTracer()
    tracing_module.set_tracer(fake_tracer)
    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(_FakeRerankClient())
    retrieve_module.set_retrieve_storage(_FakeRetrieveStorage([_chunk()]))
    set_generate_client(_FakeGenerateClient())
    chat_storage_module.set_chat_storage(_FakeChatStorage())

    async for _ in stream_module.stream_chat(
        user_jwt="t", user_id="u1", session_id="session-1", query="q"
    ):
        pass

    span_names = [name for name, _parent in fake_tracer.opened if name != "chat_turn"]
    assert span_names == EXPECTED_SPANS_IN_ORDER

    root_id = next(
        parent for name, parent in fake_tracer.opened if name == "embed_query"
    )
    assert root_id == "chat_turn"
    # every one of the six nests directly under chat_turn, not under
    # each other — matches the real trace's flat-under-root shape.
    for name, parent in fake_tracer.opened:
        if name == "chat_turn":
            continue
        assert parent == "chat_turn", f"{name} nested under {parent}, not chat_turn"


@pytest.mark.asyncio
async def test_trace_id_is_persisted_on_the_assistant_message():
    fake_tracer = _FakeTracer()
    tracing_module.set_tracer(fake_tracer)
    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_rerank_client(_FakeRerankClient())
    retrieve_module.set_retrieve_storage(_FakeRetrieveStorage([_chunk()]))
    set_generate_client(_FakeGenerateClient())
    chat_storage = _FakeChatStorage()
    chat_storage_module.set_chat_storage(chat_storage)

    async for _ in stream_module.stream_chat(
        user_jwt="t", user_id="u1", session_id="session-1", query="q"
    ):
        pass

    assistant_messages = [m for m in chat_storage.messages if m["role"] == "assistant"]
    assert assistant_messages[0]["trace_id"] == "fake-trace-id-123"


def test_get_tracer_never_raises_without_real_credentials():
    # No Langfuse env vars set in this test process — confirmed live
    # that the real SDK degrades to a safe no-op client rather than
    # raising (Stage 1.8 conversation record). This just guards that
    # get_tracer() itself doesn't add a crash on top of that.
    tracer = tracing_module.get_tracer()
    with tracer.start_as_current_observation(as_type="span", name="probe") as span:
        span.update(output={"x": 1})
    assert tracer.get_current_trace_id() is None
