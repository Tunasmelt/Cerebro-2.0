"""Stage 4.3 — storage-level tests for the real SupabaseTodoStorage
against a fake httpx transport, same pattern as
test_stage_4_2_kanban_storage.py. Focused on the one piece of real
logic this module owns: completed_at is derived from the completed
flip, not trusted from the client, and a completed todo really
persists (a fresh fetch, not just the PATCH response, shows it).
"""
import json as _json

import httpx
import pytest

from app.core.todo_storage import SupabaseTodoStorage


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.todos = {}
        self._next_id = 1
        self.patch_calls: list[tuple[str, dict]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if path == "/rest/v1/todos" and request.method == "POST":
            body = _json.loads(request.content)
            todo_id = f"todo-{self._next_id}"
            self._next_id += 1
            row = {"id": todo_id, "completed": False, "completed_at": None, **body}
            self.todos[todo_id] = row
            return httpx.Response(201, json=[row])

        if path == "/rest/v1/todos" and request.method == "GET":
            user_id = params.get("user_id", "").removeprefix("eq.")
            matches = [t for t in self.todos.values() if t["user_id"] == user_id]
            return httpx.Response(200, json=matches)

        if path == "/rest/v1/todos" and request.method == "PATCH":
            todo_id = params.get("id", "").removeprefix("eq.")
            body = _json.loads(request.content)
            self.patch_calls.append((todo_id, body))
            if todo_id not in self.todos:
                return httpx.Response(200, json=[])
            self.todos[todo_id].update(body)
            return httpx.Response(200, json=[self.todos[todo_id]])

        if path == "/rest/v1/todos" and request.method == "DELETE":
            todo_id = params.get("id", "").removeprefix("eq.")
            existed = todo_id in self.todos
            self.todos.pop(todo_id, None)
            return httpx.Response(200, json=[{"id": todo_id}] if existed else [])

        raise AssertionError(f"unexpected {request.method} {path} {params}")


def _patch_client(monkeypatch, transport: _FakeTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


@pytest.mark.asyncio
async def test_completing_a_todo_derives_completed_at_server_side(monkeypatch):
    """completed_at must never be trusted from the client — this
    module derives it from the completed flip itself."""
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseTodoStorage()

    todo = await storage.create_todo(user_jwt="t", user_id="u1", title="Do the thing", document_id=None)
    updated = await storage.update_todo(user_jwt="t", todo_id=todo["id"], updates={"completed": True})

    assert updated["completed"] is True
    assert updated["completed_at"] is not None
    # And what was actually sent to PostgREST included the derived
    # timestamp, not just the raw completed flag.
    _, patch_body = transport.patch_calls[0]
    assert patch_body["completed"] is True
    assert patch_body["completed_at"] is not None


@pytest.mark.asyncio
async def test_uncompleting_a_todo_clears_completed_at(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseTodoStorage()

    todo = await storage.create_todo(user_jwt="t", user_id="u1", title="Do the thing", document_id=None)
    await storage.update_todo(user_jwt="t", todo_id=todo["id"], updates={"completed": True})
    reverted = await storage.update_todo(user_jwt="t", todo_id=todo["id"], updates={"completed": False})

    assert reverted["completed"] is False
    assert reverted["completed_at"] is None


@pytest.mark.asyncio
async def test_completion_persists_across_a_subsequent_fetch(monkeypatch):
    """The exit criteria's "persist" behavior, proven at the layer that
    actually talks to Postgres — a fresh list_todos call, not the
    PATCH's own response."""
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseTodoStorage()

    todo = await storage.create_todo(user_jwt="t", user_id="u1", title="Persist me", document_id=None)
    await storage.update_todo(user_jwt="t", todo_id=todo["id"], updates={"completed": True})

    todos = await storage.list_todos(user_jwt="t", user_id="u1")
    reloaded = next(t for t in todos if t["id"] == todo["id"])
    assert reloaded["completed"] is True
    assert reloaded["completed_at"] is not None


@pytest.mark.asyncio
async def test_update_todo_returns_none_when_not_found(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseTodoStorage()

    result = await storage.update_todo(user_jwt="t", todo_id="missing", updates={"completed": True})
    assert result is None


@pytest.mark.asyncio
async def test_delete_todo_removes_it(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseTodoStorage()

    todo = await storage.create_todo(user_jwt="t", user_id="u1", title="Gone soon", document_id=None)
    deleted = await storage.delete_todo(user_jwt="t", todo_id=todo["id"])
    assert deleted is True

    todos = await storage.list_todos(user_jwt="t", user_id="u1")
    assert todo["id"] not in [t["id"] for t in todos]


@pytest.mark.asyncio
async def test_delete_todo_returns_false_when_not_found(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseTodoStorage()

    deleted = await storage.delete_todo(user_jwt="t", todo_id="missing")
    assert deleted is False
