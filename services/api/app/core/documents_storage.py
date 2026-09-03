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
    "text/markdown": "md",
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

SIGNED_URL_TTL_SECONDS = 60  # short-lived — a fresh signed URL is one
# API call away for a legitimate request; there's no reason for a link
# handed to the browser to remain valid longer than it takes to use it.

MAX_CAPTURE_CHARS = 20_000  # a captured thought, not a document upload —
# there's no Storage bucket size limit backstopping this one (Stage
# 5.5's whole point is no Storage round-trip for pure text capture), so
# this cap is the real enforcement, not just fast client-side feedback
# the way MAX_UPLOAD_BYTES is for the file-upload path.


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


class DocumentsStorageError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class DocumentsStorage(Protocol):
    async def authorize(
        self, *, user_jwt: str, user_id: str, title: str, mime: str
    ) -> SignedUpload: ...

    async def confirm(
        self, *, user_jwt: str, user_id: str, document_id: str
    ) -> ConfirmedUpload: ...

    async def list_documents(
        self, *, user_jwt: str, user_id: str
    ) -> list[dict[str, Any]]: ...

    async def get_document(
        self, *, user_jwt: str, document_id: str
    ) -> dict[str, Any] | None: ...

    async def get_titles(
        self, *, user_jwt: str, document_ids: list[str]
    ) -> dict[str, str]: ...

    async def get_signed_url(
        self, *, user_jwt: str, document_id: str, variant: str
    ) -> str: ...

    async def delete_document(self, *, user_jwt: str, document_id: str) -> bool: ...

    async def rename_document(
        self, *, user_jwt: str, document_id: str, title: str
    ) -> bool: ...

    async def create_capture(
        self, *, user_jwt: str, user_id: str, title: str, text: str
    ) -> str: ...


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

    async def list_documents(
        self, *, user_jwt: str, user_id: str
    ) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/documents",
                headers=self._headers(user_jwt),
                params={
                    "user_id": f"eq.{user_id}",
                    "select": "id,title,mime,size_bytes,original_size_bytes,status,created_at",
                    "order": "created_at.desc",
                },
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="documents_list_failed")
        return response.json()

    async def get_document(
        self, *, user_jwt: str, document_id: str
    ) -> dict[str, Any] | None:
        async with httpx.AsyncClient() as client:
            doc_resp = await client.get(
                f"{self._supabase_url}/rest/v1/documents",
                headers=self._headers(user_jwt),
                params={
                    "id": f"eq.{document_id}",
                    "select": "id,title,mime,size_bytes,status,created_at",
                },
            )
            if doc_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="document_lookup_failed")
            doc_rows = doc_resp.json()
            if not doc_rows:
                return None
            document = doc_rows[0]

            job_resp = await client.get(
                f"{self._supabase_url}/rest/v1/ingest_jobs",
                headers=self._headers(user_jwt),
                params={
                    "document_id": f"eq.{document_id}",
                    "select": "state,last_error",
                },
            )
            if job_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="ingest_job_lookup_failed")
            job_rows = job_resp.json()

        document["ingest_state"] = job_rows[0]["state"] if job_rows else None
        document["last_error"] = job_rows[0]["last_error"] if job_rows else None
        return document

    async def get_titles(
        self, *, user_jwt: str, document_ids: list[str]
    ) -> dict[str, str]:
        """Bulk id -> title lookup, RLS-scoped like every other query here
        (a foreign document_id just resolves to nothing, not an error).
        Same shape chat/storage.py's get_messages and chat/playground.py
        already built inline for their own citation/badge display — this
        is that pattern made reusable instead of a third copy, for
        Retrieval quality's chat/stream.py use: labeling each context
        block with its real source document name (see chat/prompt.py's
        build_system_instruction)."""
        if not document_ids:
            return {}
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/documents",
                headers=self._headers(user_jwt),
                params={"id": f"in.({','.join(document_ids)})", "select": "id,title"},
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="document_titles_lookup_failed")
        return {d["id"]: d["title"] for d in response.json()}

    async def get_signed_url(
        self, *, user_jwt: str, document_id: str, variant: str
    ) -> str:
        bucket, path_column = (
            ("indexed", "storage_path")
            if variant == "indexed"
            else ("originals", "original_storage_path")
        )
        async with httpx.AsyncClient() as client:
            document = await self._get_document(client, user_jwt, document_id)
            if document is None:
                raise DocumentsStorageError("not_found", "Document not found")
            # Sealing (Stage 3.3) only ever removed plaintext from
            # `chunks` — the underlying Storage object was never
            # re-encrypted. A signed URL bypasses the passphrase
            # entirely, so this has to fail closed here; there is no
            # unlock-claim mechanism that gates raw Storage bytes yet.
            if document["status"] == "sealed":
                raise DocumentsStorageError(
                    "document_sealed", "This document is sealed and cannot be downloaded"
                )
            path = document.get(path_column)
            if not path:
                raise DocumentsStorageError(
                    "not_available", f"No {variant} file available for this document yet"
                )

            sign_resp = await client.post(
                f"{self._supabase_url}/storage/v1/object/sign/{bucket}/{path}",
                headers=self._headers(user_jwt),
                json={"expiresIn": SIGNED_URL_TTL_SECONDS},
            )
            if sign_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="signed_url_failed")
            signed_path = sign_resp.json()["signedURL"]

        return f"{self._supabase_url}/storage/v1{signed_path}"

    async def delete_document(self, *, user_jwt: str, document_id: str) -> bool:
        async with httpx.AsyncClient() as client:
            document = await self._get_document(client, user_jwt, document_id)
            if document is None:
                return False

            # Best-effort — a Storage delete failure shouldn't block
            # removing the row the user actually asked to delete; an
            # orphaned Storage object with no documents row pointing to
            # it is inert (unreachable, never surfaced by any route).
            for bucket, path in (
                ("indexed", document.get("storage_path")),
                ("originals", document.get("original_storage_path")),
            ):
                if not path:
                    continue
                await client.request(
                    "DELETE",
                    f"{self._supabase_url}/storage/v1/object/{bucket}",
                    headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                    json={"prefixes": [path]},
                )

            delete_resp = await client.delete(
                f"{self._supabase_url}/rest/v1/documents",
                headers=self._headers(user_jwt),
                params={"id": f"eq.{document_id}"},
            )
            if delete_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="document_delete_failed")

        return True

    async def rename_document(
        self, *, user_jwt: str, document_id: str, title: str
    ) -> bool:
        """`Prefer: return=representation` on the PATCH is what lets a
        "not this caller's document" (RLS makes it invisible, matched
        zero rows) be told apart from a real update — same 404-not-403
        pattern delete_session (chat/storage.py) uses for the same
        reason. Works regardless of status (processing/ready/sealed) —
        renaming is a metadata-only change, never touches chunk content,
        so it's safe even on a sealed document."""
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self._supabase_url}/rest/v1/documents",
                headers={**self._headers(user_jwt), "Prefer": "return=representation"},
                params={"id": f"eq.{document_id}"},
                json={"title": title},
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="document_rename_failed")
        return bool(response.json())

    async def create_capture(
        self, *, user_jwt: str, user_id: str, title: str, text: str
    ) -> str:
        """Stage 5.5 — no signed URL, no PUT, no confirm: a captured
        thought has no file at all, so this is the entire "upload" for
        this source type in one call. `captured_text` is the only place
        this text exists before extract.py chunks it — there's no
        Storage object to read it back from. `ingest_jobs.state` starts
        at 'extracting' (not 'uploading'/'normalizing'), reflecting that
        both of those stages are genuinely skipped for this source
        type, not just fast-pathed through."""
        async with httpx.AsyncClient() as client:
            doc_resp = await client.post(
                f"{self._supabase_url}/rest/v1/documents",
                headers={
                    **self._headers(user_jwt),
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                json={
                    "user_id": user_id,
                    "title": title,
                    "mime": "text/plain",
                    "size_bytes": len(text.encode("utf-8")),
                    "status": "processing",
                    "source": "capture",
                    "captured_text": text,
                },
            )
            if doc_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="capture_insert_failed")
            document_id = doc_resp.json()[0]["id"]

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
                    "state": "extracting",
                },
            )
            if job_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="ingest_job_insert_failed")

        return document_id


_storage: DocumentsStorage = SupabaseDocumentsStorage()


def get_documents_storage() -> DocumentsStorage:
    return _storage


def set_documents_storage(storage: DocumentsStorage) -> None:
    """Test seam — inject a fake storage/DB client."""
    global _storage
    _storage = storage
