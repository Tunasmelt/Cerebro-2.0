"""Stage 1.7 — chat session/message persistence. Stage 2.4 adds the read
side (list_sessions, get_messages) needed to reopen a past conversation
and replay its graph pulse — chat_messages.retrieved_chunk_ids only
stores chunk ids, not document ids, so get_messages resolves them via
one extra query against chunks rather than requiring N+1 lookups or a
denormalized document_ids column that could drift from the real chunk
ids if a document were ever deleted.

Chat management pass (delete/export/dedicated page): a real gap was
found here, not just a missing feature — Stage 2.4's own replay UI only
ever re-fires the graph pulse from `retrieved_document_ids`; it never
reconstructed the actual citation numbering/document titles for a past
message, so a reopened conversation could show *which* documents lit up
but never the assistant's real text with working citation chips, live
or otherwise. `get_messages` now resolves real per-message citations
using the exact same `extract_citations` a live turn uses (see below) —
not a second, drifting reimplementation.
"""
import os
from typing import Any, Protocol


from app.core.http_client import CachedHttpClientMixin
from app.chat.prompt import extract_citations
from app.retrieve.retrieve import RetrievedChunk


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
    async def get_recent_messages(
        self, *, user_jwt: str, session_id: str, limit: int
    ) -> list[dict[str, Any]]: ...
    async def delete_session(self, *, user_jwt: str, session_id: str) -> bool: ...


class SupabaseChatStorage(CachedHttpClientMixin):
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
        client = self._client()
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
        client = self._client()
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
        client = self._client()
        response = await client.post(
            f"{self._supabase_url}/rest/v1/chat_messages",
            headers=self._headers(user_jwt),
            json=body,
        )
        if response.status_code >= 400:
            raise ChatStorageError("message_save_failed", response.text)

    PREVIEW_MAX_CHARS = 80

    async def list_sessions(self, *, user_jwt: str) -> list[dict[str, Any]]:
        client = self._client()
        sessions_resp = await client.get(
            f"{self._supabase_url}/rest/v1/chat_sessions",
            headers=self._headers(user_jwt),
            params={"select": "id,created_at", "order": "created_at.desc"},
        )
        if sessions_resp.status_code >= 400:
            raise ChatStorageError("list_sessions_failed", sessions_resp.text)
        sessions = sessions_resp.json()
        if not sessions:
            return []

        # One extra query for every session's earliest user message,
        # not N+1 — grouped in Python below to keep just the first
        # per session_id (order.asc means the first row seen per
        # session_id is the earliest).
        session_ids = ",".join(s["id"] for s in sessions)
        preview_resp = await client.get(
            f"{self._supabase_url}/rest/v1/chat_messages",
            headers=self._headers(user_jwt),
            params={
                "session_id": f"in.({session_ids})",
                "role": "eq.user",
                "select": "session_id,content,created_at",
                "order": "created_at.asc",
            },
        )
        if preview_resp.status_code >= 400:
            raise ChatStorageError("list_sessions_preview_failed", preview_resp.text)

        earliest_by_session: dict[str, str] = {}
        for row in preview_resp.json():
            if row["session_id"] not in earliest_by_session:
                earliest_by_session[row["session_id"]] = row["content"]

        for s in sessions:
            content = earliest_by_session.get(s["id"])
            s["preview"] = (
                (content[: self.PREVIEW_MAX_CHARS] + "…")
                if content and len(content) > self.PREVIEW_MAX_CHARS
                else content
            )
        return sessions

    async def get_messages(
        self, *, user_jwt: str, session_id: str
    ) -> list[dict[str, Any]] | None:
        client = self._client()
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

        # Titles are new here — the original Stage 2.4 read only ever
        # needed document *ids* (to pulse graph nodes), never titles.
        # A real chat-transcript view needs a human-readable label
        # for each citation chip.
        document_titles: dict[str, str] = {}
        document_ids = sorted(set(chunk_to_document.values()))
        if document_ids:
            docs_in_list = ",".join(document_ids)
            docs_resp = await client.get(
                f"{self._supabase_url}/rest/v1/documents",
                headers=self._headers(user_jwt),
                params={"id": f"in.({docs_in_list})", "select": "id,title"},
            )
            if docs_resp.status_code >= 400:
                raise ChatStorageError("resolve_document_titles_failed", docs_resp.text)
            document_titles = {d["id"]: d["title"] for d in docs_resp.json()}

        for m in messages:
            chunk_ids = m.get("retrieved_chunk_ids") or []
            m["retrieved_document_ids"] = sorted(
                {chunk_to_document[cid] for cid in chunk_ids if cid in chunk_to_document}
            )
            if m["role"] != "assistant":
                m["citations"] = []
                continue
            # The exact same extract_citations a live turn uses
            # (chat/prompt.py) — not a second, drifting reimplementation.
            # It only reads .chunk_id/.document_id off each item, so
            # lightweight stand-ins are enough; there's no need to
            # refetch chunk content just to re-derive citation order.
            retrieved_stand_ins = [
                RetrievedChunk(
                    chunk_id=cid,
                    document_id=chunk_to_document[cid],
                    ordinal=0,
                    content="",
                    meta={},
                    relevance_score=0.0,
                )
                for cid in chunk_ids
                if cid in chunk_to_document
            ]
            m["citations"] = [
                {
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "document_title": document_titles.get(c.document_id, "Untitled document"),
                }
                for c in extract_citations(m["content"], retrieved_stand_ins)
            ]
        return messages

    async def get_recent_messages(
        self, *, user_jwt: str, session_id: str, limit: int
    ) -> list[dict[str, Any]]:
        """Stage 5.1 — a lighter read than get_messages: role/content
        only, no retrieved_document_ids resolution (that join exists for
        Stage 2.4's replay UI, not for feeding a cheap rewrite call).
        Fetched newest-first (cheapest way to get "the last N") then
        reversed to chronological order, matching the shape
        rewrite.rewrite_query expects."""
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/rest/v1/chat_messages",
            headers=self._headers(user_jwt),
            params={
                "session_id": f"eq.{session_id}",
                "select": "role,content",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )
        if response.status_code >= 400:
            raise ChatStorageError("fetch_recent_messages_failed", response.text)
        return list(reversed(response.json()))

    async def delete_session(self, *, user_jwt: str, session_id: str) -> bool:
        """chat_messages.session_id already cascades on delete (Stage
        0.2's original schema) — deleting the session row is the whole
        operation. RLS scopes the DELETE itself, so a session that isn't
        the caller's own just deletes zero rows rather than erroring —
        `Prefer: return=representation` is what lets this method tell
        "deleted" from "not found/not owned" apart."""
        client = self._client()
        response = await client.delete(
            f"{self._supabase_url}/rest/v1/chat_sessions",
            headers={**self._headers(user_jwt), "Prefer": "return=representation"},
            params={"id": f"eq.{session_id}"},
        )
        if response.status_code >= 400:
            raise ChatStorageError("delete_session_failed", response.text)
        return bool(response.json())


_storage: ChatStorage = SupabaseChatStorage()


def get_chat_storage() -> ChatStorage:
    return _storage


def set_chat_storage(storage: ChatStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage
