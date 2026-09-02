"""Stage 4.2 — storage-level tests for the real SupabaseKanbanStorage
against a fake httpx transport, same pattern as
test_stage_3_5_seal_storage.py / test_stage_3_6_document_storage.py.

The required exit-criteria test — "reordering persists across a page
reload" — is proven here at the layer that actually talks to Postgres:
a card PATCHed with a new column/position is exactly what a subsequent
GET /boards/{id} (get_board_with_cards) returns, ordered by position.
"""
import json as _json

import httpx
import pytest

from app.core.kanban_storage import SupabaseKanbanStorage


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.boards = {"board-1": {"id": "board-1", "title": "My Board", "columns": ["Backlog", "Done"], "created_at": "t"}}
        self.cards = {}
        self._next_id = 1
        self.patch_calls: list[tuple[str, dict]] = []
        self.board_lookup_calls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if path == "/rest/v1/boards" and request.method == "POST":
            body = _json.loads(request.content)
            row = {"id": "board-new", "user_id": body["user_id"], "title": body["title"], "columns": ["Backlog", "In Progress", "Done"], "created_at": "t"}
            return httpx.Response(201, json=[row])

        if path == "/rest/v1/boards" and request.method == "GET":
            self.board_lookup_calls.append(params.get("id", ""))
            board_id = params.get("id", "").removeprefix("eq.")
            board = self.boards.get(board_id)
            return httpx.Response(200, json=[board] if board else [])

        if path == "/rest/v1/cards" and request.method == "GET":
            board_id = params.get("board_id", "").removeprefix("eq.")
            column = params.get("column_name")
            matches = [c for c in self.cards.values() if c["board_id"] == board_id]
            if column:
                matches = [c for c in matches if c["column_name"] == column.removeprefix("eq.")]
            matches.sort(key=lambda c: c["position"], reverse="desc" in params.get("order", ""))
            limit = params.get("limit")
            if limit:
                matches = matches[: int(limit)]
            return httpx.Response(200, json=matches)

        if path == "/rest/v1/cards" and request.method == "POST":
            body = _json.loads(request.content)
            card_id = f"card-{self._next_id}"
            self._next_id += 1
            row = {"id": card_id, **body}
            self.cards[card_id] = row
            return httpx.Response(201, json=[row])

        if path == "/rest/v1/cards" and request.method == "PATCH":
            card_id = params.get("id", "").removeprefix("eq.")
            body = _json.loads(request.content)
            self.patch_calls.append((card_id, body))
            if card_id not in self.cards:
                return httpx.Response(200, json=[])
            self.cards[card_id].update(body)
            return httpx.Response(200, json=[self.cards[card_id]])

        if path == "/rest/v1/cards" and request.method == "DELETE":
            card_id = params.get("id", "").removeprefix("eq.")
            existed = card_id in self.cards
            self.cards.pop(card_id, None)
            return httpx.Response(200, json=[{"id": card_id}] if existed else [])

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
async def test_create_card_appends_to_the_end_of_an_empty_column(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseKanbanStorage()

    card = await storage.create_card(
        user_jwt="t", user_id="u1", board_id="board-1", column_name="Backlog",
        title="First card", description="", document_id=None,
    )
    assert card["position"] == 0


@pytest.mark.asyncio
async def test_create_card_appends_after_existing_cards_in_the_column(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseKanbanStorage()

    await storage.create_card(
        user_jwt="t", user_id="u1", board_id="board-1", column_name="Backlog",
        title="First", description="", document_id=None,
    )
    second = await storage.create_card(
        user_jwt="t", user_id="u1", board_id="board-1", column_name="Backlog",
        title="Second", description="", document_id=None,
    )
    assert second["position"] == 1000


@pytest.mark.asyncio
async def test_create_card_rejects_a_board_id_not_visible_to_the_caller(monkeypatch):
    """Regression test: create_card must verify board ownership (via an
    RLS-scoped lookup) BEFORE ever attempting the position lookup or
    the insert — Stage 4.1's cards_insert_own RLS policy alone doesn't
    stop a caller from attaching a card (with their own user_id) to a
    board_id they don't own, since it only checks the new row's own
    user_id, not board_id's owner."""
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseKanbanStorage()

    card = await storage.create_card(
        user_jwt="t", user_id="u1", board_id="not-my-board", column_name="Backlog",
        title="Shouldn't be created", description="", document_id=None,
    )

    assert card is None
    assert transport.board_lookup_calls == ["eq.not-my-board"]
    assert transport.cards == {}  # no position lookup, no insert


@pytest.mark.asyncio
async def test_reordering_persists_across_a_subsequent_fetch(monkeypatch):
    """The required exit-criteria test: move a card to a new column at a
    specific position, then fetch the board fresh (as a page reload
    would) and confirm the change is really there — not just returned
    by the PATCH response."""
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseKanbanStorage()

    card = await storage.create_card(
        user_jwt="t", user_id="u1", board_id="board-1", column_name="Backlog",
        title="Move me", description="", document_id=None,
    )
    card_id = card["id"]

    await storage.update_card(
        user_jwt="t", card_id=card_id, updates={"column_name": "Done", "position": 42.5}
    )

    # Simulates a page reload: a completely fresh fetch, not the PATCH's
    # own response.
    board = await storage.get_board_with_cards(user_jwt="t", board_id="board-1")
    reloaded_card = next(c for c in board["cards"] if c["id"] == card_id)
    assert reloaded_card["column_name"] == "Done"
    assert reloaded_card["position"] == 42.5


@pytest.mark.asyncio
async def test_get_board_with_cards_orders_by_position(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseKanbanStorage()

    c1 = await storage.create_card(user_jwt="t", user_id="u1", board_id="board-1", column_name="Backlog", title="A", description="", document_id=None)
    c2 = await storage.create_card(user_jwt="t", user_id="u1", board_id="board-1", column_name="Backlog", title="B", description="", document_id=None)
    # Insert c2 between c1 (0) and... nothing yet — just move it before c1.
    await storage.update_card(user_jwt="t", card_id=c2["id"], updates={"position": -1})

    board = await storage.get_board_with_cards(user_jwt="t", board_id="board-1")
    ids_in_order = [c["id"] for c in board["cards"]]
    assert ids_in_order == [c2["id"], c1["id"]]


@pytest.mark.asyncio
async def test_get_board_with_cards_returns_none_when_not_found(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseKanbanStorage()

    board = await storage.get_board_with_cards(user_jwt="t", board_id="missing")
    assert board is None


@pytest.mark.asyncio
async def test_delete_card_returns_false_when_not_found(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseKanbanStorage()

    deleted = await storage.delete_card(user_jwt="t", card_id="missing")
    assert deleted is False


@pytest.mark.asyncio
async def test_delete_card_removes_it(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseKanbanStorage()

    card = await storage.create_card(user_jwt="t", user_id="u1", board_id="board-1", column_name="Backlog", title="Gone soon", description="", document_id=None)
    deleted = await storage.delete_card(user_jwt="t", card_id=card["id"])
    assert deleted is True

    board = await storage.get_board_with_cards(user_jwt="t", board_id="board-1")
    assert card["id"] not in [c["id"] for c in board["cards"]]
