"""Stage 1.7 — chat session/message persistence.

chat_sessions/chat_messages already existed in the schema before this
stage (supabase/migrations/0001) — chat_messages.retrieved_chunk_ids is
what lets a past conversation replay its graph pulse animation later
(Phase 2's retrieval-replay), so every assistant turn's real retrieved
chunk ids are stored, not just the final answer text.
"""
import os
from typing import Any, Protocol

import httpx


class ChatStorageError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class ChatStorage(Protocol):
    async def create_session(self, *, user_jwt: str, user_id: str) -> str: ...
    async def get_session(
        self, *, user_jwt: str, session_id: str
    ) -> dict[str, Any] | None: ...
    async def save_message(
        self,
        *,
        user_jwt: str,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        retrieved_chunk_ids: list[str],
        trace_id: str | None = None,
    ) -> None: ...


class SupabaseChatStorage:
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {user_jwt}",
            "Content-Type": "application/json",
        }

    async def create_session(self, *, user_jwt: str, user_id: str) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._supabase_url}/rest/v1/chat_sessions",
                headers={**self._headers(user_jwt), "Prefer": "return=representation"},
                json={"user_id": user_id},
            )
        if response.status_code >= 400:
            raise ChatStorageError("session_create_failed", response.text)
        return response.json()[0]["id"]

    async def get_session(
        self, *, user_jwt: str, session_id: str
    ) -> dict[str, Any] | None:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/chat_sessions",
                headers=self._headers(user_jwt),
                params={"id": f"eq.{session_id}", "select": "id"},
            )
        rows = response.json()
        return rows[0] if rows else None

    async def save_message(
        self,
        *,
        user_jwt: str,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        retrieved_chunk_ids: list[str],
        trace_id: str | None = None,
    ) -> None:
        body = {
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "retrieved_chunk_ids": retrieved_chunk_ids,
        }
        if trace_id is not None:
            body["trace_id"] = trace_id
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._supabase_url}/rest/v1/chat_messages",
                headers=self._headers(user_jwt),
                json=body,
            )
        if response.status_code >= 400:
            raise ChatStorageError("message_save_failed", response.text)


_storage: ChatStorage = SupabaseChatStorage()


def get_chat_storage() -> ChatStorage:
    return _storage


def set_chat_storage(storage: ChatStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage
