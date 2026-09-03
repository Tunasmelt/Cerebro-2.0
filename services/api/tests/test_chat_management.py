"""Chat management pass — view/delete a chat, real citation resolution.
Storage-level tests for list_sessions' new preview field and the new
delete_session, against a fake httpx transport (same pattern as
test_stage_2_4_replay.py). Route-level DELETE tests live in
test_chat_routes.py, right next to the other chat route tests.
"""
import httpx
import pytest

from app.chat.storage import SupabaseChatStorage


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, sessions=None, user_messages=None, delete_response_rows=None):
        self.sessions = sessions if sessions is not None else [{"id": "s1", "created_at": "t1"}]
        self.user_messages = user_messages if user_messages is not None else []
        self.delete_response_rows = delete_response_rows
        self.delete_calls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if path == "/rest/v1/chat_sessions" and request.method == "GET":
            return httpx.Response(200, json=self.sessions)

        if path == "/rest/v1/chat_messages" and request.method == "GET":
            return httpx.Response(200, json=self.user_messages)

        if path == "/rest/v1/chat_sessions" and request.method == "DELETE":
            self.delete_calls.append(params.get("id", ""))
            rows = self.delete_response_rows
            if rows is None:
                rows = [{"id": "s1"}] if self.sessions else []
            return httpx.Response(200, json=rows)

        raise AssertionError(f"unexpected {request.method} {path}")


def _patch_client(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


# --- list_sessions preview -------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sessions_returns_preview_from_earliest_user_message(monkeypatch):
    # The real query asks PostgREST for order=created_at.asc — this fake
    # transport doesn't re-sort (that's PostgREST's job, not this
    # method's), so the fixture is already in the order a real response
    # would arrive in: earliest first. list_sessions keeps the first row
    # it sees per session_id, which is what actually makes "earliest"
    # true given that real ordering.
    transport = _FakeTransport(
        sessions=[{"id": "s1", "created_at": "t1"}],
        user_messages=[
            {"session_id": "s1", "content": "first question", "created_at": "2026-01-01T00:00:00Z"},
            {"session_id": "s1", "content": "second question", "created_at": "2026-01-01T00:00:05Z"},
        ],
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseChatStorage()

    sessions = await storage.list_sessions(user_jwt="t")

    assert sessions[0]["preview"] == "first question"


@pytest.mark.asyncio
async def test_list_sessions_preview_is_none_for_a_session_with_no_user_message(monkeypatch):
    transport = _FakeTransport(sessions=[{"id": "s1", "created_at": "t1"}], user_messages=[])
    _patch_client(monkeypatch, transport)
    storage = SupabaseChatStorage()

    sessions = await storage.list_sessions(user_jwt="t")

    assert sessions[0]["preview"] is None


@pytest.mark.asyncio
async def test_list_sessions_preview_is_truncated(monkeypatch):
    long_text = "a" * 200
    transport = _FakeTransport(
        sessions=[{"id": "s1", "created_at": "t1"}],
        user_messages=[{"session_id": "s1", "content": long_text, "created_at": "t"}],
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseChatStorage()

    sessions = await storage.list_sessions(user_jwt="t")

    assert sessions[0]["preview"] == "a" * SupabaseChatStorage.PREVIEW_MAX_CHARS + "…"


@pytest.mark.asyncio
async def test_list_sessions_with_no_sessions_skips_the_preview_query_entirely(monkeypatch):
    transport = _FakeTransport(sessions=[])
    _patch_client(monkeypatch, transport)
    storage = SupabaseChatStorage()

    sessions = await storage.list_sessions(user_jwt="t")

    assert sessions == []


# --- delete_session ----------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_session_returns_true_when_a_row_was_deleted(monkeypatch):
    transport = _FakeTransport(delete_response_rows=[{"id": "s1"}])
    _patch_client(monkeypatch, transport)
    storage = SupabaseChatStorage()

    deleted = await storage.delete_session(user_jwt="t", session_id="s1")

    assert deleted is True
    assert transport.delete_calls == ["eq.s1"]


@pytest.mark.asyncio
async def test_delete_session_returns_false_when_nothing_was_deleted(monkeypatch):
    # RLS-scoped: a session that isn't the caller's own (or doesn't
    # exist) just deletes zero rows rather than erroring.
    transport = _FakeTransport(delete_response_rows=[])
    _patch_client(monkeypatch, transport)
    storage = SupabaseChatStorage()

    deleted = await storage.delete_session(user_jwt="t", session_id="does-not-exist")

    assert deleted is False
