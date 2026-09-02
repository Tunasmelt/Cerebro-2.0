"""Stage 4.3 — todo CRUD routes.

Exit criteria: tasks create, complete, persist, collapse into completed
section. "Collapse into completed section" is a frontend concern driven
by the `completed` field this API already returns — nothing extra
needed at this layer. Same fake-storage seam pattern as
test_stage_4_2_kanban_routes.py.
"""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core import todo_storage as storage_module
from app.main import app

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"
TEST_SUB = "11111111-1111-1111-1111-111111111111"


class _StubJWKClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self._key)


class _FakeTodoStorage:
    def __init__(self):
        self.todo_to_create: dict | None = None
        self.todos_to_list: list[dict] = []
        self.todo_to_update: dict | None = None
        self.delete_result = True
        self.update_calls: list[tuple[str, dict]] = []

    async def create_todo(self, *, user_jwt, user_id, title, document_id):
        return self.todo_to_create

    async def list_todos(self, *, user_jwt, user_id):
        return self.todos_to_list

    async def update_todo(self, *, user_jwt, todo_id, updates):
        self.update_calls.append((todo_id, updates))
        return self.todo_to_update

    async def delete_todo(self, *, user_jwt, todo_id):
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
    storage_module.set_todo_storage(storage_module.SupabaseTodoStorage())


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


def test_create_todo(client, keypair):
    private_key, _ = keypair
    fake = _FakeTodoStorage()
    fake.todo_to_create = {
        "id": "todo-1", "title": "Water the plants", "completed": False,
        "completed_at": None, "document_id": None,
    }
    storage_module.set_todo_storage(fake)

    response = client.post("/api/v1/todos", headers=auth_headers(private_key), json={"title": "Water the plants"})

    assert response.status_code == 201
    assert response.json()["id"] == "todo-1"
    assert response.json()["completed"] is False


def test_create_todo_with_document_reference_chip(client, keypair):
    private_key, _ = keypair
    fake = _FakeTodoStorage()
    fake.todo_to_create = {"id": "todo-1", "document_id": "doc-1"}
    storage_module.set_todo_storage(fake)

    response = client.post(
        "/api/v1/todos", headers=auth_headers(private_key),
        json={"title": "Read this", "document_id": "doc-1"},
    )
    assert response.status_code == 201
    assert response.json()["document_id"] == "doc-1"


def test_create_todo_requires_auth(client):
    storage_module.set_todo_storage(_FakeTodoStorage())
    assert client.post("/api/v1/todos", json={"title": "x"}).status_code == 401


def test_list_todos(client, keypair):
    private_key, _ = keypair
    fake = _FakeTodoStorage()
    fake.todos_to_list = [{"id": "todo-1", "title": "x", "completed": False}]
    storage_module.set_todo_storage(fake)

    response = client.get("/api/v1/todos", headers=auth_headers(private_key))
    assert response.status_code == 200
    assert response.json()["todos"] == fake.todos_to_list


def test_list_todos_requires_auth(client):
    storage_module.set_todo_storage(_FakeTodoStorage())
    assert client.get("/api/v1/todos").status_code == 401


def test_complete_a_todo_via_patch(client, keypair):
    """Required behavior: a task completes via PATCH."""
    private_key, _ = keypair
    fake = _FakeTodoStorage()
    fake.todo_to_update = {"id": "todo-1", "completed": True, "completed_at": "2026-01-01T00:00:00Z"}
    storage_module.set_todo_storage(fake)

    response = client.patch("/api/v1/todos/todo-1", headers=auth_headers(private_key), json={"completed": True})

    assert response.status_code == 200
    assert response.json()["completed"] is True
    assert fake.update_calls == [("todo-1", {"completed": True})]


def test_uncomplete_a_todo_via_patch_with_false(client, keypair):
    """completed=False must actually be sent, not dropped as falsy —
    exclude_none, not exclude_unset/exclude_falsy."""
    private_key, _ = keypair
    fake = _FakeTodoStorage()
    fake.todo_to_update = {"id": "todo-1", "completed": False}
    storage_module.set_todo_storage(fake)

    response = client.patch("/api/v1/todos/todo-1", headers=auth_headers(private_key), json={"completed": False})

    assert response.status_code == 200
    assert fake.update_calls == [("todo-1", {"completed": False})]


def test_patch_todo_not_found_returns_404(client, keypair):
    private_key, _ = keypair
    fake = _FakeTodoStorage()
    fake.todo_to_update = None
    storage_module.set_todo_storage(fake)

    response = client.patch("/api/v1/todos/missing", headers=auth_headers(private_key), json={"completed": True})
    assert response.status_code == 404


def test_patch_with_no_fields_returns_422(client, keypair):
    private_key, _ = keypair
    storage_module.set_todo_storage(_FakeTodoStorage())

    response = client.patch("/api/v1/todos/todo-1", headers=auth_headers(private_key), json={})
    assert response.status_code == 422


def test_delete_todo(client, keypair):
    private_key, _ = keypair
    fake = _FakeTodoStorage()
    fake.delete_result = True
    storage_module.set_todo_storage(fake)

    response = client.delete("/api/v1/todos/todo-1", headers=auth_headers(private_key))
    assert response.status_code == 200
    assert response.json() == {"id": "todo-1", "deleted": True}


def test_delete_todo_not_found_returns_404(client, keypair):
    private_key, _ = keypair
    fake = _FakeTodoStorage()
    fake.delete_result = False
    storage_module.set_todo_storage(fake)

    response = client.delete("/api/v1/todos/missing", headers=auth_headers(private_key))
    assert response.status_code == 404


def test_todo_mutation_routes_require_auth(client):
    storage_module.set_todo_storage(_FakeTodoStorage())
    assert client.patch("/api/v1/todos/todo-1", json={"completed": True}).status_code == 401
    assert client.delete("/api/v1/todos/todo-1").status_code == 401
