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
                "content": "X is Y",
                "retrieved_chunk_ids": ["c1", "c2", "c3"],
                "created_at": "2026-01-01T00:00:01Z",
            },
        ]
        # c1 and c2 both belong to d1 (multiple chunks retrieved from the
        # same document must collapse to one document id, not duplicate
        # pulses for the same node); c3 belongs to d2. c-missing (never
        # requested here) would represent a deleted chunk.
        self.chunk_to_doc = {"c1": "d1", "c2": "d1", "c3": "d2"}

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
    assert assistant_msg["retrieved_document_ids"] == ["d1", "d2"]


@pytest.mark.asyncio
async def test_get_messages_returns_none_for_nonexistent_session(_patch_httpx_client):
    _patch_httpx_client.session_exists = False
    storage = SupabaseChatStorage()
    messages = await storage.get_messages(user_jwt="t", session_id="ghost")
    assert messages is None
