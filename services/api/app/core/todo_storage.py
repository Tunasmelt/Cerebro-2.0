"""Stage 4.3 — todo CRUD. Flat, board-independent list (a `todos` row
has no board_id — Stage 4.1's schema keeps kanban and todos as two
separate tables sharing only `user_id`, same as the exit criteria's own
framing of them as distinct features). "Complete" is just a PATCH
setting `completed` — and this module is what actually derives
`completed_at` from that flip, so the frontend never has to construct a
timestamp itself.
"""
import os
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx
from fastapi import HTTPException


class TodoStorage(Protocol):
    async def create_todo(
        self, *, user_jwt: str, user_id: str, title: str, document_id: str | None
    ) -> dict[str, Any]: ...

    async def list_todos(self, *, user_jwt: str, user_id: str) -> list[dict[str, Any]]: ...

    async def update_todo(
        self, *, user_jwt: str, todo_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def delete_todo(self, *, user_jwt: str, todo_id: str) -> bool: ...


class SupabaseTodoStorage:
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {user_jwt}",
            "Content-Type": "application/json",
        }

    async def create_todo(
        self, *, user_jwt: str, user_id: str, title: str, document_id: str | None
    ) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._supabase_url}/rest/v1/todos",
                headers={**self._headers(user_jwt), "Prefer": "return=representation"},
                json={"user_id": user_id, "title": title, "document_id": document_id},
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="todo_create_failed")
        return response.json()[0]

    async def list_todos(self, *, user_jwt: str, user_id: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/todos",
                headers=self._headers(user_jwt),
                params={
                    "user_id": f"eq.{user_id}",
                    "select": "id,title,completed,completed_at,document_id,created_at",
                    "order": "created_at.desc",
                },
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="todos_list_failed")
        return response.json()

    async def update_todo(
        self, *, user_jwt: str, todo_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        body = dict(updates)
        if "completed" in body:
            # Derived here, not trusted from the client — completed_at
            # always reflects the moment this toggle actually happened,
            # and always clears on uncomplete rather than being left
            # stale from a previous completion.
            body["completed_at"] = (
                datetime.now(timezone.utc).isoformat() if body["completed"] else None
            )

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self._supabase_url}/rest/v1/todos",
                headers={**self._headers(user_jwt), "Prefer": "return=representation"},
                params={"id": f"eq.{todo_id}"},
                json=body,
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="todo_update_failed")
        rows = response.json()
        return rows[0] if rows else None

    async def delete_todo(self, *, user_jwt: str, todo_id: str) -> bool:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self._supabase_url}/rest/v1/todos",
                headers={**self._headers(user_jwt), "Prefer": "return=representation"},
                params={"id": f"eq.{todo_id}"},
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="todo_delete_failed")
        return bool(response.json())


_storage: TodoStorage = SupabaseTodoStorage()


def get_todo_storage() -> TodoStorage:
    return _storage


def set_todo_storage(storage: TodoStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage
