"""Stage 4.2 — kanban CRUD and drag-drop. Cards live in one flat `cards`
table (Stage 4.1); "moving between columns" and "reordering" are both
just a PATCH changing `column_name` and/or `position` — there's no
separate move/reorder endpoint, since both are the same operation from
the DB's point of view. `position` is a float specifically so the
frontend can insert a card between two neighbors by averaging their
positions client-side, without this module ever renumbering a column.
"""
import os
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import HTTPException

from app.core.http_client import CachedHttpClientMixin

@dataclass
class Board:
    id: str
    user_id: str
    title: str
    columns: list[str]
    created_at: str


class KanbanStorage(Protocol):
    async def create_board(self, *, user_jwt: str, user_id: str, title: str) -> Board: ...

    async def list_boards(self, *, user_jwt: str, user_id: str) -> list[dict[str, Any]]: ...

    async def get_board_with_cards(
        self, *, user_jwt: str, board_id: str
    ) -> dict[str, Any] | None: ...

    async def create_card(
        self,
        *,
        user_jwt: str,
        user_id: str,
        board_id: str,
        column_name: str,
        title: str,
        description: str,
        document_id: str | None,
    ) -> dict[str, Any] | None: ...

    async def update_card(
        self, *, user_jwt: str, card_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def delete_card(self, *, user_jwt: str, card_id: str) -> bool: ...


class SupabaseKanbanStorage(CachedHttpClientMixin):
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {user_jwt}",
            "Content-Type": "application/json",
        }

    async def create_board(self, *, user_jwt: str, user_id: str, title: str) -> Board:
        client = self._client()
        response = await client.post(
            f"{self._supabase_url}/rest/v1/boards",
            headers={**self._headers(user_jwt), "Prefer": "return=representation"},
            json={"user_id": user_id, "title": title},
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="board_create_failed")
        row = response.json()[0]
        return Board(
            id=row["id"],
            user_id=row["user_id"],
            title=row["title"],
            columns=row["columns"],
            created_at=row["created_at"],
        )

    async def list_boards(self, *, user_jwt: str, user_id: str) -> list[dict[str, Any]]:
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/rest/v1/boards",
            headers=self._headers(user_jwt),
            params={
                "user_id": f"eq.{user_id}",
                "select": "id,title,columns,created_at",
                "order": "created_at.desc",
            },
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="boards_list_failed")
        return response.json()

    async def get_board_with_cards(
        self, *, user_jwt: str, board_id: str
    ) -> dict[str, Any] | None:
        client = self._client()
        board_resp = await client.get(
            f"{self._supabase_url}/rest/v1/boards",
            headers=self._headers(user_jwt),
            params={"id": f"eq.{board_id}", "select": "id,title,columns,created_at"},
        )
        if board_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="board_lookup_failed")
        board_rows = board_resp.json()
        if not board_rows:
            return None
        board = board_rows[0]

        cards_resp = await client.get(
            f"{self._supabase_url}/rest/v1/cards",
            headers=self._headers(user_jwt),
            params={
                "board_id": f"eq.{board_id}",
                "select": "id,column_name,title,description,position,document_id,created_at",
                "order": "position.asc",
            },
        )
        if cards_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="cards_list_failed")

        board["cards"] = cards_resp.json()
        return board

    async def create_card(
        self,
        *,
        user_jwt: str,
        user_id: str,
        board_id: str,
        column_name: str,
        title: str,
        description: str,
        document_id: str | None,
    ) -> dict[str, Any] | None:
        client = self._client()
        # Stage 4.1's cards_insert_own RLS policy only checks
        # `user_id = auth.uid()` on the NEW row — it has no way to
        # also validate that board_id belongs to that same user,
        # since a WITH CHECK clause can't easily cross-reference
        # another table. Without this explicit lookup, any
        # authenticated caller could attach a card (with their own
        # user_id) to any board_id they can guess, since the insert
        # itself would still pass RLS. This GET is what actually
        # enforces "you can only add cards to your own board" —
        # same RLS-scoped-lookup pattern as get_board_with_cards.
        board_resp = await client.get(
            f"{self._supabase_url}/rest/v1/boards",
            headers=self._headers(user_jwt),
            params={"id": f"eq.{board_id}", "select": "id"},
        )
        if board_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="board_lookup_failed")
        if not board_resp.json():
            return None

        # New cards go to the end of their column — one extra read
        # to find the current max position, then +1000 (a large,
        # arbitrary gap so later drag-drop reorders have room to
        # insert between cards by averaging without ever colliding).
        max_resp = await client.get(
            f"{self._supabase_url}/rest/v1/cards",
            headers=self._headers(user_jwt),
            params={
                "board_id": f"eq.{board_id}",
                "column_name": f"eq.{column_name}",
                "select": "position",
                "order": "position.desc",
                "limit": 1,
            },
        )
        if max_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="card_position_lookup_failed")
        max_rows = max_resp.json()
        next_position = (max_rows[0]["position"] + 1000) if max_rows else 0

        create_resp = await client.post(
            f"{self._supabase_url}/rest/v1/cards",
            headers={**self._headers(user_jwt), "Prefer": "return=representation"},
            json={
                "board_id": board_id,
                "user_id": user_id,
                "column_name": column_name,
                "title": title,
                "description": description,
                "document_id": document_id,
                "position": next_position,
            },
        )
        if create_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="card_create_failed")
        return create_resp.json()[0]

    async def update_card(
        self, *, user_jwt: str, card_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        client = self._client()
        response = await client.patch(
            f"{self._supabase_url}/rest/v1/cards",
            headers={**self._headers(user_jwt), "Prefer": "return=representation"},
            params={"id": f"eq.{card_id}"},
            json=updates,
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="card_update_failed")
        rows = response.json()
        return rows[0] if rows else None

    async def delete_card(self, *, user_jwt: str, card_id: str) -> bool:
        client = self._client()
        response = await client.delete(
            f"{self._supabase_url}/rest/v1/cards",
            headers={**self._headers(user_jwt), "Prefer": "return=representation"},
            params={"id": f"eq.{card_id}"},
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="card_delete_failed")
        return bool(response.json())


_storage: KanbanStorage = SupabaseKanbanStorage()


def get_kanban_storage() -> KanbanStorage:
    return _storage


def set_kanban_storage(storage: KanbanStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage
