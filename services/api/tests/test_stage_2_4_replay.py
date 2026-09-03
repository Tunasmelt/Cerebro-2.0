"""Stage 2.4 — retrieval-replay animation (backend half).

Exit criteria: reopening a past conversation replays the same pulse
from stored retrieved_chunk_ids. chat_messages only stores chunk ids,
not document ids, so get_messages must resolve them — this file tests
that resolution logic directly against a fake httpx transport, since
the real logic lives entirely inside SupabaseChatStorage.get_messages.
"""
import httpx
import pytest

from app.chat.storage import SupabaseChatStorage


# Real chunk-id markers must be UUID-shaped — chat/prompt.py's
# _CITATION_RE only matches a 36-char id, same as every real chunk id
# in production. Short fixture ids like "c1" would silently never match
# at all, which is exactly what broke the first draft of these tests.
C1 = "c1111111-1111-1111-1111-111111111111"
C2 = "c2222222-2222-2222-2222-222222222222"
C3 = "c3333333-3333-3333-3333-333333333333"
D1 = "d1111111-1111-1111-1111-111111111111"
D2 = "d2222222-2222-2222-2222-222222222222"


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.session_exists = True
        self.messages = [
            {
                "id": "m1",
                "role": "user",
                "content": "what is X?",
                "retrieved_chunk_ids": [],
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "m2",
                "role": "assistant",
                "content": f"X is Y [[chunk:{C1}]], also see [[chunk:{C3}]].",
                "retrieved_chunk_ids": [C1, C2, C3],
                "created_at": "2026-01-01T00:00:01Z",
            },
        ]
        # c1 and c2 both belong to d1 (multiple chunks retrieved from the
        # same document must collapse to one document id, not duplicate
        # pulses for the same node); c3 belongs to d2. c-missing (never
        # requested here) would represent a deleted chunk.
        self.chunk_to_doc = {C1: D1, C2: D1, C3: D2}
        self.doc_titles = {D1: "raft-paper.pdf", D2: "note.md"}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/v1/chat_sessions":
            if not self.session_exists:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{"id": "session-1"}])
        if path == "/rest/v1/chat_messages":
            return httpx.Response(200, json=self.messages)
        if path == "/rest/v1/chunks":
            query = str(request.url.params.get("id", ""))
            # e.g. "in.(c1,c2,c3)"
            ids = query.removeprefix("in.(").removesuffix(")").split(",")
            rows = [
                {"id": cid, "document_id": self.chunk_to_doc[cid]}
                for cid in ids
                if cid in self.chunk_to_doc
            ]
            return httpx.Response(200, json=rows)
        if path == "/rest/v1/documents":
            query = str(request.url.params.get("id", ""))
            ids = query.removeprefix("in.(").removesuffix(")").split(",")
            rows = [
                {"id": did, "title": self.doc_titles[did]}
                for did in ids
                if did in self.doc_titles
            ]
            return httpx.Response(200, json=rows)
        raise AssertionError(f"unexpected request to {path}")


@pytest.fixture(autouse=True)
def _patch_httpx_client(monkeypatch):
    transport = _FakeTransport()

    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    return transport


@pytest.mark.asyncio
async def test_get_messages_resolves_chunk_ids_to_document_ids(_patch_httpx_client):
    storage = SupabaseChatStorage()
    messages = await storage.get_messages(user_jwt="t", session_id="session-1")

    assert messages is not None
    user_msg, assistant_msg = messages
    assert user_msg["retrieved_document_ids"] == []
    # c1 and c2 both resolve to d1 — collapsed to one entry, not two.
    assert assistant_msg["retrieved_document_ids"] == sorted([D1, D2])


@pytest.mark.asyncio
async def test_get_messages_returns_none_for_nonexistent_session(_patch_httpx_client):
    _patch_httpx_client.session_exists = False
    storage = SupabaseChatStorage()
    messages = await storage.get_messages(user_jwt="t", session_id="ghost")
    assert messages is None


# --- Chat management pass: real citation resolution on reopen -------------------


@pytest.mark.asyncio
async def test_get_messages_resolves_real_citations_with_titles_in_first_appearance_order(
    _patch_httpx_client,
):
    storage = SupabaseChatStorage()
    messages = await storage.get_messages(user_jwt="t", session_id="session-1")

    assistant_msg = messages[1]
    assert assistant_msg["citations"] == [
        {"chunk_id": C1, "document_id": D1, "document_title": "raft-paper.pdf"},
        {"chunk_id": C3, "document_id": D2, "document_title": "note.md"},
    ]


@pytest.mark.asyncio
async def test_get_messages_citations_empty_for_user_messages(_patch_httpx_client):
    storage = SupabaseChatStorage()
    messages = await storage.get_messages(user_jwt="t", session_id="session-1")

    assert messages[0]["role"] == "user"
    assert messages[0]["citations"] == []


@pytest.mark.asyncio
async def test_get_messages_drops_a_marker_for_a_chunk_that_was_never_retrieved(
    _patch_httpx_client,
):
    # Same distrust-by-default contract extract_citations already
    # enforces for a live turn: a marker naming an id outside the
    # retrieved set (hallucinated, or a real-looking id that just never
    # came back from retrieval) must not become a citation.
    never_retrieved = "00000000-0000-0000-0000-000000000000"
    _patch_httpx_client.messages[1]["content"] = (
        f"See [[chunk:{C1}]] and [[chunk:{never_retrieved}]]."
    )
    storage = SupabaseChatStorage()
    messages = await storage.get_messages(user_jwt="t", session_id="session-1")

    assistant_msg = messages[1]
    assert [c["chunk_id"] for c in assistant_msg["citations"]] == [C1]
