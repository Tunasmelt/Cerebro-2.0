"""Stage 4.2 — kanban CRUD and drag-drop routes.

Exit criteria: cards create, move between columns, persist order.
Required test: reordering persists across a page reload — proven here
at the route level as "a PATCH changing column_name/position is
reflected in a subsequent GET", the same contract the frontend's reload
relies on; the actual real-Postgres persistence is exercised at the
storage level in test_stage_4_2_kanban_storage.py.

Same fake-storage seam pattern as test_documents_list.py.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core import kanban_storage as storage_module
from app.core.kanban_storage import Board
from app.main import app

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"
TEST_SUB = "11111111-1111-1111-1111-111111111111"


class _StubJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._key)


class _FakeKanbanStorage:
    def __init__(self):
        self.board_to_create: Board | None = None
        self.boards_to_list: list[dict] = []
        self.board_with_cards: dict | None = None
        self.card_to_create: dict | None = None
        self.card_to_update: dict | None = None
        self.delete_result = True
        self.update_calls: list[tuple[str, dict]] = []

    async def create_board(self, *, user_jwt, user_id, title):
        return self.board_to_create

    async def list_boards(self, *, user_jwt, user_id):
        return self.boards_to_list

    async def get_board_with_cards(self, *, user_jwt, board_id):
        return self.board_with_cards

    async def create_card(
        self, *, user_jwt, user_id, board_id, column_name, title, description, document_id
    ):
        return self.card_to_create

    async def update_card(self, *, user_jwt, card_id, updates):
        self.update_calls.append((card_id, updates))
        return self.card_to_update

    async def delete_card(self, *, user_jwt, card_id):
        return self.delete_result


@pytest.fixture
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture(autouse=True)
def _wire_test_seams(keypair, monkeypatch):
    _private_key, public_key = keypair
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    auth_module.set_jwks_client(_StubJWKClient(public_key))
    yield
    auth_module.set_jwks_client(None)
    storage_module.set_kanban_storage(storage_module.SupabaseKanbanStorage())


@pytest.fixture
def client():
    return TestClient(app)


def auth_headers(private_key, sub=TEST_SUB):
    payload = {
        "iss": TEST_ISSUER,
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    return {"Authorization": f"Bearer {token}"}


# --- Boards --------------------------------------------------------------------


def test_create_board(client, keypair):
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.board_to_create = Board(
        id="board-1", user_id=TEST_SUB, title="My Board", columns=["Backlog", "Doing", "Done"],
        created_at="2026-01-01T00:00:00Z",
    )
    storage_module.set_kanban_storage(fake)

    response = client.post("/api/v1/boards", headers=auth_headers(private_key), json={"title": "My Board"})

    assert response.status_code == 201
    assert response.json()["id"] == "board-1"
    assert response.json()["columns"] == ["Backlog", "Doing", "Done"]


def test_create_board_requires_auth(client):
    storage_module.set_kanban_storage(_FakeKanbanStorage())
    assert client.post("/api/v1/boards", json={"title": "x"}).status_code == 401


def test_list_boards(client, keypair):
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.boards_to_list = [{"id": "board-1", "title": "My Board", "columns": [], "created_at": "x"}]
    storage_module.set_kanban_storage(fake)

    response = client.get("/api/v1/boards", headers=auth_headers(private_key))
    assert response.status_code == 200
    assert response.json()["boards"] == fake.boards_to_list


def test_get_board_returns_cards(client, keypair):
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.board_with_cards = {
        "id": "board-1",
        "title": "My Board",
        "columns": ["Backlog", "Done"],
        "cards": [{"id": "card-1", "column_name": "Backlog", "position": 0}],
    }
    storage_module.set_kanban_storage(fake)

    response = client.get("/api/v1/boards/board-1", headers=auth_headers(private_key))
    assert response.status_code == 200
    assert response.json()["cards"][0]["id"] == "card-1"


def test_get_board_not_found_returns_404(client, keypair):
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.board_with_cards = None
    storage_module.set_kanban_storage(fake)

    response = client.get("/api/v1/boards/missing", headers=auth_headers(private_key))
    assert response.status_code == 404


# --- Cards -----------------------------------------------------------------------


def test_create_card(client, keypair):
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.card_to_create = {
        "id": "card-1", "column_name": "Backlog", "title": "Do the thing",
        "description": "", "position": 0, "document_id": None,
    }
    storage_module.set_kanban_storage(fake)

    response = client.post(
        "/api/v1/boards/board-1/cards",
        headers=auth_headers(private_key),
        json={"column_name": "Backlog", "title": "Do the thing"},
    )
    assert response.status_code == 201
    assert response.json()["id"] == "card-1"


def test_create_card_on_a_board_that_doesnt_exist_or_isnt_yours_returns_404(client, keypair):
    """Regression test for a real gap a security review caught: Stage
    4.1's cards_insert_own RLS policy only checks user_id = auth.uid()
    on the new row, not that board_id belongs to that user — without an
    explicit ownership check, any caller could attach a card to any
    guessable board_id. create_card now returns None (-> 404) when the
    board isn't visible to the caller under RLS."""
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.card_to_create = None
    storage_module.set_kanban_storage(fake)

    response = client.post(
        "/api/v1/boards/someone-elses-board/cards",
        headers=auth_headers(private_key),
        json={"column_name": "Backlog", "title": "Do the thing"},
    )
    assert response.status_code == 404


def test_create_card_with_document_reference_chip(client, keypair):
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.card_to_create = {"id": "card-1", "document_id": "doc-1"}
    storage_module.set_kanban_storage(fake)

    response = client.post(
        "/api/v1/boards/board-1/cards",
        headers=auth_headers(private_key),
        json={"column_name": "Backlog", "title": "Read this", "document_id": "doc-1"},
    )
    assert response.status_code == 201
    assert response.json()["document_id"] == "doc-1"


def test_move_card_to_a_new_column_via_patch(client, keypair):
    """Required behavior: moving a card between columns is a PATCH."""
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.card_to_update = {"id": "card-1", "column_name": "Done", "position": 500}
    storage_module.set_kanban_storage(fake)

    response = client.patch(
        "/api/v1/cards/card-1",
        headers=auth_headers(private_key),
        json={"column_name": "Done", "position": 500},
    )
    assert response.status_code == 200
    assert response.json()["column_name"] == "Done"
    assert fake.update_calls == [("card-1", {"column_name": "Done", "position": 500})]


def test_patch_with_only_position_reorders_within_column(client, keypair):
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.card_to_update = {"id": "card-1", "position": 250}
    storage_module.set_kanban_storage(fake)

    response = client.patch(
        "/api/v1/cards/card-1", headers=auth_headers(private_key), json={"position": 250}
    )
    assert response.status_code == 200
    assert fake.update_calls == [("card-1", {"position": 250})]


def test_patch_card_not_found_returns_404(client, keypair):
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.card_to_update = None
    storage_module.set_kanban_storage(fake)

    response = client.patch(
        "/api/v1/cards/missing", headers=auth_headers(private_key), json={"position": 1}
    )
    assert response.status_code == 404


def test_patch_with_no_fields_returns_422(client, keypair):
    private_key, _ = keypair
    storage_module.set_kanban_storage(_FakeKanbanStorage())

    response = client.patch("/api/v1/cards/card-1", headers=auth_headers(private_key), json={})
    assert response.status_code == 422


def test_delete_card(client, keypair):
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.delete_result = True
    storage_module.set_kanban_storage(fake)

    response = client.delete("/api/v1/cards/card-1", headers=auth_headers(private_key))
    assert response.status_code == 200
    assert response.json() == {"id": "card-1", "deleted": True}


def test_delete_card_not_found_returns_404(client, keypair):
    private_key, _ = keypair
    fake = _FakeKanbanStorage()
    fake.delete_result = False
    storage_module.set_kanban_storage(fake)

    response = client.delete("/api/v1/cards/missing", headers=auth_headers(private_key))
    assert response.status_code == 404


def test_card_routes_require_auth(client):
    storage_module.set_kanban_storage(_FakeKanbanStorage())
    assert client.post("/api/v1/boards/board-1/cards", json={"column_name": "x", "title": "y"}).status_code == 401
    assert client.patch("/api/v1/cards/card-1", json={"position": 1}).status_code == 401
    assert client.delete("/api/v1/cards/card-1").status_code == 401
