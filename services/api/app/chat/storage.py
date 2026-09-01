"""Stage 1.7 — chat session/message persistence. Stage 2.4 adds the read
side (list_sessions, get_messages) needed to reopen a past conversation
and replay its graph pulse — chat_messages.retrieved_chunk_ids only
stores chunk ids, not document ids, so get_messages resolves them via
one extra query against chunks rather than requiring N+1 lookups or a
denormalized document_ids column that could drift from the real chunk
ids if a document were ever deleted.
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
    async def list_sessions(self, *, user_jwt: str) -> list[dict[str, Any]]: ...
    async def get_messages(
        self, *, user_jwt: str, session_id: str
    ) -> list[dict[str, Any]] | None: ...


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

    async def list_sessions(self, *, user_jwt: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/chat_sessions",
                headers=self._headers(user_jwt),
                params={"select": "id,created_at", "order": "created_at.desc"},
            )
        if response.status_code >= 400:
            raise ChatStorageError("list_sessions_failed", response.text)
        return response.json()

    async def get_messages(
        self, *, user_jwt: str, session_id: str
    ) -> list[dict[str, Any]] | None:
        async with httpx.AsyncClient() as client:
            session_resp = await client.get(
                f"{self._supabase_url}/rest/v1/chat_sessions",
                headers=self._headers(user_jwt),
                params={"id": f"eq.{session_id}", "select": "id"},
            )
            if session_resp.status_code >= 400:
                raise ChatStorageError("fetch_session_failed", session_resp.text)
            if not session_resp.json():
                return None

            messages_resp = await client.get(
                f"{self._supabase_url}/rest/v1/chat_messages",
                headers=self._headers(user_jwt),
                params={
                    "session_id": f"eq.{session_id}",
                    "select": "id,role,content,retrieved_chunk_ids,created_at",
                    "order": "created_at.asc",
                },
            )
            if messages_resp.status_code >= 400:
                raise ChatStorageError("fetch_messages_failed", messages_resp.text)
            messages = messages_resp.json()

            all_chunk_ids = sorted(
                {cid for m in messages for cid in (m.get("retrieved_chunk_ids") or [])}
            )
            chunk_to_document: dict[str, str] = {}
            if all_chunk_ids:
                in_list = ",".join(all_chunk_ids)
                chunks_resp = await client.get(
                    f"{self._supabase_url}/rest/v1/chunks",
                    headers=self._headers(user_jwt),
                    params={"id": f"in.({in_list})", "select": "id,document_id"},
                )
                if chunks_resp.status_code >= 400:
                    raise ChatStorageError("resolve_chunk_documents_failed", chunks_resp.text)
                chunk_to_document = {c["id"]: c["document_id"] for c in chunks_resp.json()}

        for m in messages:
            chunk_ids = m.get("retrieved_chunk_ids") or []
            m["retrieved_document_ids"] = sorted(
                {chunk_to_document[cid] for cid in chunk_ids if cid in chunk_to_document}
            )
        return messages


_storage: ChatStorage = SupabaseChatStorage()


def get_chat_storage() -> ChatStorage:
    return _storage


def set_chat_storage(storage: ChatStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage
