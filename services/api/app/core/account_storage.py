"""Stage 4.7 — account data wipe (the settings page's "Delete account"
action). Wipes every application-data row the caller owns — documents
(and everything that cascades from them: chunks, sealed_chunks,
ingest_jobs, document_clusters, document_edges, unlock_claims), boards
(cascades cards), todos, chat_sessions (cascades chat_messages), and
clusters — the last one needed its own explicit delete rather than
riding a cascade: document_clusters cascades FROM a clusters row being
deleted, not the other way around, so without this a user's cluster
rows (label, centroid coordinates derived from their own document
embeddings) would silently survive a "delete everything."

Deliberately does NOT delete the `auth.users` row itself: that requires
Supabase's service-role key, which this project has never used anywhere
— every route so far authenticates every Supabase call with the
caller's own JWT, RLS is the real enforcement boundary. Introducing a
service-role secret is a real architecture change, not something to
slip in as a side effect of a settings page. So this wipes all data and
leaves an empty, still-sign-in-able account — an honest partial
feature, not silently passed off as full account deletion (the route
and the UI copy both say so).
"""
import os
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.http_client import CachedHttpClientMixin
from app.core.documents_storage import get_documents_storage


class AccountStorage(CachedHttpClientMixin):
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {user_jwt}",
            "Content-Type": "application/json",
        }

    async def _bulk_delete(
        self, client: httpx.AsyncClient, user_jwt: str, table: str, user_id: str
    ) -> None:
        response = await client.delete(
            f"{self._supabase_url}/rest/v1/{table}",
            headers=self._headers(user_jwt),
            params={"user_id": f"eq.{user_id}"},
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"{table}_wipe_failed")

    async def wipe_account_data(self, *, user_jwt: str, user_id: str) -> dict[str, Any]:
        documents_storage = get_documents_storage()
        documents = await documents_storage.list_documents(user_jwt=user_jwt, user_id=user_id)

        # Reuses Stage 3.6's real per-document delete (Storage objects
        # + row, which cascades chunks/sealed_chunks/ingest_jobs/
        # document_clusters/document_edges/unlock_claims) rather than a
        # second, untested path that could drift from it.
        for document in documents:
            await documents_storage.delete_document(user_jwt=user_jwt, document_id=document["id"])

        client = self._client()
        # boards cascades cards; chat_sessions cascades chat_messages.
        # clusters (Stage 2.1) has its own user_id FK to auth.users
        # and isn't cascaded by anything else here — document_clusters
        # cascades FROM a clusters delete, not the other way around,
        # so it needed its own explicit delete (a real gap a security
        # review caught: without this, a user's cluster rows —
        # label, centroid coordinates derived from their own document
        # embeddings — survived a "delete everything" indefinitely).
        await self._bulk_delete(client, user_jwt, "boards", user_id)
        await self._bulk_delete(client, user_jwt, "todos", user_id)
        await self._bulk_delete(client, user_jwt, "chat_sessions", user_id)
        await self._bulk_delete(client, user_jwt, "clusters", user_id)

        return {"documents_deleted": len(documents)}


_storage = AccountStorage()


def get_account_storage() -> AccountStorage:
    return _storage


def set_account_storage(storage: AccountStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage
