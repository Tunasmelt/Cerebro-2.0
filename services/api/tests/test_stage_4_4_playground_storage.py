"""Storage-level tests for Stage 4.4's ChatPlaygroundStorage — exercises
the real HTTP-wiring logic against a fake httpx transport, proving the
breakdown reconstructs real chunk content/document titles and applies
the correct 404-vs-not-found rules.
"""
import httpx
import pytest

from app.chat import generate as generate_module
from app.chat.generate import GenerateError
from app.chat.playground import ChatPlaygroundStorage


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, sessions, messages, chunks, documents):
        self._sessions = sessions
        self._messages = messages
        self._chunks = chunks
        self._documents = documents

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if path == "/rest/v1/chat_sessions":
            session_id = params["id"].removeprefix("eq.")
            rows = [s for s in self._sessions if s["id"] == session_id]
            return httpx.Response(200, json=rows)

        if path == "/rest/v1/chat_messages":
            session_id = params["session_id"].removeprefix("eq.")
            rows = [m for m in self._messages if m["session_id"] == session_id]
            return httpx.Response(200, json=rows)

        if path == "/rest/v1/chunks":
            ids = params["id"].removeprefix("in.(").rstrip(")").split(",")
            rows = [c for c in self._chunks if c["id"] in ids]
            return httpx.Response(200, json=rows)

        if path == "/rest/v1/documents":
            ids = params["id"].removeprefix("in.(").rstrip(")").split(",")
            rows = [d for d in self._documents if d["id"] in ids]
            return httpx.Response(200, json=rows)

        raise AssertionError(f"unexpected {request.method} {path}")


def _patch_client(monkeypatch, transport: _FakeTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


@pytest.mark.asyncio
async def test_breakdown_reconstructs_real_chunk_content_and_document_titles(monkeypatch):
    transport = _FakeTransport(
        sessions=[{"id": "s1"}],
        messages=[
            {
                "id": "u1",
                "session_id": "s1",
                "role": "user",
                "content": "how does raft work?",
                "retrieved_chunk_ids": None,
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "m1",
                "session_id": "s1",
                "role": "assistant",
                "content": "raft uses a leader [[chunk:c1]]",
                "retrieved_chunk_ids": ["c1"],
                "created_at": "2026-01-01T00:00:01Z",
            },
        ],
        chunks=[
            {
                "id": "c1",
                "document_id": "d1",
                "ordinal": 0,
                "content": "Raft elects a single leader.",
                "meta": {},
            }
        ],
        documents=[{"id": "d1", "title": "raft-paper.pdf"}],
    )
    _patch_client(monkeypatch, transport)

    storage = ChatPlaygroundStorage()
    breakdown = await storage.get_prompt_breakdown(
        user_jwt="t", session_id="s1", message_id="m1"
    )

    assert breakdown is not None
    context_sections = [s for s in breakdown["sections"] if s["label"] == "context"]
    assert len(context_sections) == 1
    assert context_sections[0]["content"] == "Raft elects a single leader."
    assert "raft-paper.pdf" in context_sections[0]["citation"]

    query_section = next(s for s in breakdown["sections"] if s["label"] == "user_query")
    assert query_section["content"] == "how does raft work?"

    assert breakdown["response"]["content"] == "raft uses a leader [[chunk:c1]]"
    assert breakdown["total_tokens"] > 0
    assert breakdown["estimated_cost_usd"] > 0


@pytest.mark.asyncio
async def test_breakdown_with_no_retrieved_chunks_still_returns_system_and_query(monkeypatch):
    transport = _FakeTransport(
        sessions=[{"id": "s1"}],
        messages=[
            {
                "id": "u1",
                "session_id": "s1",
                "role": "user",
                "content": "irrelevant question",
                "retrieved_chunk_ids": None,
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "m1",
                "session_id": "s1",
                "role": "assistant",
                "content": "no relevant context was found",
                "retrieved_chunk_ids": [],
                "created_at": "2026-01-01T00:00:01Z",
            },
        ],
        chunks=[],
        documents=[],
    )
    _patch_client(monkeypatch, transport)

    storage = ChatPlaygroundStorage()
    breakdown = await storage.get_prompt_breakdown(
        user_jwt="t", session_id="s1", message_id="m1"
    )

    assert breakdown is not None
    labels = [s["label"] for s in breakdown["sections"]]
    assert labels == ["system_instructions", "user_query"]


@pytest.mark.asyncio
async def test_breakdown_for_user_role_message_returns_none(monkeypatch):
    transport = _FakeTransport(
        sessions=[{"id": "s1"}],
        messages=[
            {
                "id": "u1",
                "session_id": "s1",
                "role": "user",
                "content": "hello",
                "retrieved_chunk_ids": None,
                "created_at": "2026-01-01T00:00:00Z",
            }
        ],
        chunks=[],
        documents=[],
    )
    _patch_client(monkeypatch, transport)

    storage = ChatPlaygroundStorage()
    breakdown = await storage.get_prompt_breakdown(
        user_jwt="t", session_id="s1", message_id="u1"
    )

    assert breakdown is None


@pytest.mark.asyncio
async def test_breakdown_for_nonexistent_session_returns_none(monkeypatch):
    transport = _FakeTransport(sessions=[], messages=[], chunks=[], documents=[])
    _patch_client(monkeypatch, transport)

    storage = ChatPlaygroundStorage()
    breakdown = await storage.get_prompt_breakdown(
        user_jwt="t", session_id="does-not-exist", message_id="m1"
    )

    assert breakdown is None


class _FakeGenerateClient:
    """Stage 5.6 — records the exact system_instruction/input_text it was
    called with, so the test can assert run_edited_prompt actually
    mirrors build_system_instruction's block-join format rather than
    inventing a second one."""

    model = "gemini-3.5-flash-lite"

    def __init__(self, *, response_text="the edited answer", error=None):
        self._response_text = response_text
        self._error = error
        self.last_call: dict | None = None

    async def stream_text(self, *, system_instruction, input_text):
        self.last_call = {"system_instruction": system_instruction, "input_text": input_text}
        if self._error:
            raise self._error
        for chunk in [self._response_text[:5], self._response_text[5:]]:
            if chunk:
                yield chunk


@pytest.mark.asyncio
async def test_run_edited_prompt_mirrors_block_join_format_and_returns_real_response(
    monkeypatch,
):
    transport = _FakeTransport(sessions=[{"id": "s1"}], messages=[], chunks=[], documents=[])
    _patch_client(monkeypatch, transport)
    fake_generate = _FakeGenerateClient()
    generate_module.set_generate_client(fake_generate)

    storage = ChatPlaygroundStorage()
    result = await storage.run_edited_prompt(
        user_jwt="t",
        session_id="s1",
        system_instructions="edited system header",
        context_sections=[{"chunk_id": "c1", "content": "edited chunk text"}],
        user_query="edited query",
    )

    assert result is not None
    assert result["response"]["content"] == "the edited answer"
    assert result["total_tokens"] > 0
    assert result["estimated_cost_usd"] > 0
    assert result["latency_ms"] >= 0
    assert fake_generate.last_call == {
        "system_instruction": "edited system header\n\n[[chunk:c1]]\nedited chunk text",
        "input_text": "edited query",
    }
    generate_module.set_generate_client(generate_module.GeminiGenerateClient())


@pytest.mark.asyncio
async def test_run_edited_prompt_with_no_context_sections_omits_block_join(monkeypatch):
    transport = _FakeTransport(sessions=[{"id": "s1"}], messages=[], chunks=[], documents=[])
    _patch_client(monkeypatch, transport)
    fake_generate = _FakeGenerateClient()
    generate_module.set_generate_client(fake_generate)

    storage = ChatPlaygroundStorage()
    await storage.run_edited_prompt(
        user_jwt="t",
        session_id="s1",
        system_instructions="just the header",
        context_sections=[],
        user_query="a query",
    )

    assert fake_generate.last_call["system_instruction"] == "just the header"
    generate_module.set_generate_client(generate_module.GeminiGenerateClient())


@pytest.mark.asyncio
async def test_run_edited_prompt_for_nonexistent_session_returns_none(monkeypatch):
    transport = _FakeTransport(sessions=[], messages=[], chunks=[], documents=[])
    _patch_client(monkeypatch, transport)

    storage = ChatPlaygroundStorage()
    result = await storage.run_edited_prompt(
        user_jwt="t",
        session_id="does-not-exist",
        system_instructions="x",
        context_sections=[],
        user_query="y",
    )

    assert result is None


@pytest.mark.asyncio
async def test_run_edited_prompt_surfaces_generate_error_without_raising(monkeypatch):
    transport = _FakeTransport(sessions=[{"id": "s1"}], messages=[], chunks=[], documents=[])
    _patch_client(monkeypatch, transport)
    fake_generate = _FakeGenerateClient(
        error=GenerateError("generate_call_failed", "upstream boom")
    )
    generate_module.set_generate_client(fake_generate)

    storage = ChatPlaygroundStorage()
    result = await storage.run_edited_prompt(
        user_jwt="t",
        session_id="s1",
        system_instructions="x",
        context_sections=[],
        user_query="y",
    )

    assert result == {"error": {"code": "generate_call_failed", "message": "upstream boom"}}
    generate_module.set_generate_client(generate_module.GeminiGenerateClient())
