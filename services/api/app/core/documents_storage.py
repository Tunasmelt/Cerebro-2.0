"""Signed-URL direct-to-storage upload flow (Stage 1.1, revised).

Vercel hard-caps function request bodies well under the documented 50MB,
so file bytes never pass through Next.js or Render — see
architecture-and-security.md §1 "Ingest pipeline" for the full flow and
why each step exists:

1. authorize(): create `documents` (status=processing) + `ingest_jobs`
   (state=uploading) FIRST, before any signed URL exists, so a storage
   object never exists without a tracked row. Returns a signed upload URL.
2. Browser PUTs bytes directly to Supabase Storage.
3. confirm(): verify the object actually exists (existence + size) via
   Supabase's own API before advancing the job past `uploading` — the
   client's "done" signal alone is never trusted.

Uses the caller's own verified JWT for Storage/PostgREST calls instead of
a service-role key — RLS enforces ownership independently of the API
layer's own checks, and no service-role secret needs to exist in Render's
env for this at all.

Real size/mime enforcement is Supabase Storage's bucket-level config
(supabase/migrations/0004_originals_bucket_limits.sql), confirmed against
current docs and live-tested — not the checks in this module, which are
fast-feedback only (a doomed upload shouldn't get as far as a signed URL).
"""
import os
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from fastapi import HTTPException

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 52,428,800 bytes — Supabase Free
# plan's hard global ceiling, binary MiB not decimal MB, empirically
# pinned to the exact byte (52428800 succeeds, 52428801 fails with
# EntityTooLarge). No headroom; raising this needs a Pro plan upgrade.
# Must match supabase/migrations/0004_originals_bucket_limits.sql exactly.

ALLOWED_MIME_TYPES = {
    "text/plain": "txt",
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


@dataclass
class Document:
    id: str
    user_id: str
    title: str
    mime: str
    status: str
    original_storage_path: str


@dataclass
class SignedUpload:
    document_id: str
    upload_url: str


@dataclass
class ConfirmedUpload:
    document_id: str
    state: str
    size_bytes: int


class DocumentsStorage(Protocol):
    async def authorize(
        self, *, user_jwt: str, user_id: str, title: str, mime: str
    ) -> SignedUpload: ...

    async def confirm(
        self, *, user_jwt: str, user_id: str, document_id: str
    ) -> ConfirmedUpload: ...


class SupabaseDocumentsStorage:
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {"apikey": self._anon_key, "Authorization": f"Bearer {user_jwt}"}

    async def _get_document(
        self, client: httpx.AsyncClient, user_jwt: str, document_id: str
    ) -> dict[str, Any] | None:
        response = await client.get(
            f"{self._supabase_url}/rest/v1/documents",
            headers=self._headers(user_jwt),
            params={"id": f"eq.{document_id}", "select": "*"},
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="document_lookup_failed")
        rows = response.json()
        return rows[0] if rows else None

    async def authorize(
        self, *, user_jwt: str, user_id: str, title: str, mime: str
    ) -> SignedUpload:
        document_id = str(uuid.uuid4())
        ext = ALLOWED_MIME_TYPES[mime]
        path = f"{user_id}/{document_id}/original.{ext}"

        async with httpx.AsyncClient() as client:
            doc_resp = await client.post(
                f"{self._supabase_url}/rest/v1/documents",
                headers={
                    **self._headers(user_jwt),
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                json={
                    "id": document_id,
                    "user_id": user_id,
                    "title": title,
                    "mime": mime,
                    "size_bytes": 0,
                    "original_storage_path": path,
                    "status": "processing",
                },
            )
            if doc_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="document_insert_failed")

            job_resp = await client.post(
                f"{self._supabase_url}/rest/v1/ingest_jobs",
                headers={
                    **self._headers(user_jwt),
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                json={
                    "document_id": document_id,
                    "user_id": user_id,
                    "state": "uploading",
                },
            )
            if job_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="ingest_job_insert_failed")

            sign_resp = await client.post(
                f"{self._supabase_url}/storage/v1/object/upload/sign/originals/{path}",
                headers=self._headers(user_jwt),
                json={},
            )
            if sign_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="signed_url_failed")
            sign_body = sign_resp.json()

        upload_url = f"{self._supabase_url}/storage/v1{sign_body['url']}"
        return SignedUpload(document_id=document_id, upload_url=upload_url)

    async def confirm(
        self, *, user_jwt: str, user_id: str, document_id: str
    ) -> ConfirmedUpload:
        async with httpx.AsyncClient() as client:
            document = await self._get_document(client, user_jwt, document_id)
            if document is None:
                raise HTTPException(status_code=404, detail="document_not_found")

            path = document["original_storage_path"]
            prefix = "/".join(path.split("/")[:-1])
            filename = path.split("/")[-1]

            list_resp = await client.post(
                f"{self._supabase_url}/storage/v1/object/list/originals",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                json={"prefix": prefix},
            )
            if list_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="storage_list_failed")

            matching = [
                obj for obj in list_resp.json() if obj.get("name") == filename
            ]
            if not matching:
                raise HTTPException(status_code=422, detail="upload_not_found")

            size_bytes = matching[0]["metadata"]["size"]
            if size_bytes > MAX_UPLOAD_BYTES:
                await client.patch(
                    f"{self._supabase_url}/rest/v1/ingest_jobs",
                    headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                    params={"document_id": f"eq.{document_id}"},
                    json={"state": "failed", "last_error": "file_too_large"},
                )
                raise HTTPException(status_code=413, detail="file_too_large")

            new_state = "normalizing"
            await client.patch(
                f"{self._supabase_url}/rest/v1/ingest_jobs",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                params={"document_id": f"eq.{document_id}"},
                json={"state": new_state},
            )
            await client.patch(
                f"{self._supabase_url}/rest/v1/documents",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                params={"id": f"eq.{document_id}"},
                json={"size_bytes": size_bytes, "original_size_bytes": size_bytes},
            )

        return ConfirmedUpload(
            document_id=document_id, state=new_state, size_bytes=size_bytes
        )


_storage: DocumentsStorage = SupabaseDocumentsStorage()


def get_documents_storage() -> DocumentsStorage:
    return _storage


def set_documents_storage(storage: DocumentsStorage) -> None:
    """Test seam — inject a fake storage/DB client."""
    global _storage
    _storage = storage
