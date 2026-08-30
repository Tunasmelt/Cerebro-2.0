"""Uploads to the `originals` bucket and the matching `documents` row.

Uses the caller's own verified JWT for both the Storage write and the
PostgREST insert, rather than a service-role key — RLS then enforces
ownership independently of the API layer's own checks (defense in depth),
and no service-role secret needs to exist in Render's env for this at all.

Path convention is the one decided in Stage 0.3:
originals/{user_id}/{document_id}/original.{ext}
"""
import os
import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx
from fastapi import HTTPException

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB — defense in depth; the Next.js
# proxy is the guaranteed enforcement point per architecture-and-security.md.

ALLOWED_MIME_TYPES = {
    "text/plain": "txt",
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


@dataclass
class UploadedDocument:
    id: str
    title: str
    mime: str
    size_bytes: int
    original_storage_path: str
    status: str


class DocumentsStorage(Protocol):
    async def upload_original(
        self, *, user_jwt: str, user_id: str, document_id: str, ext: str,
        content: bytes, mime: str,
    ) -> str: ...

    async def insert_document(
        self, *, user_jwt: str, user_id: str, document_id: str, title: str,
        mime: str, size_bytes: int, original_storage_path: str,
    ) -> UploadedDocument: ...


class SupabaseDocumentsStorage:
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {"apikey": self._anon_key, "Authorization": f"Bearer {user_jwt}"}

    async def upload_original(
        self, *, user_jwt: str, user_id: str, document_id: str, ext: str,
        content: bytes, mime: str,
    ) -> str:
        path = f"{user_id}/{document_id}/original.{ext}"
        url = f"{self._supabase_url}/storage/v1/object/originals/{path}"
        headers = {**self._headers(user_jwt), "Content-Type": mime}
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, content=content)
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="storage_upload_failed")
        return path

    async def insert_document(
        self, *, user_jwt: str, user_id: str, document_id: str, title: str,
        mime: str, size_bytes: int, original_storage_path: str,
    ) -> UploadedDocument:
        url = f"{self._supabase_url}/rest/v1/documents"
        headers = {
            **self._headers(user_jwt),
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        body = {
            "id": document_id,
            "user_id": user_id,
            "title": title,
            "mime": mime,
            "size_bytes": size_bytes,
            "original_storage_path": original_storage_path,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=body)
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="document_insert_failed")
        row = response.json()[0]
        return UploadedDocument(
            id=row["id"],
            title=row["title"],
            mime=row["mime"],
            size_bytes=row["size_bytes"],
            original_storage_path=row["original_storage_path"],
            status=row["status"],
        )


_storage: DocumentsStorage = SupabaseDocumentsStorage()


def get_documents_storage() -> DocumentsStorage:
    return _storage


def set_documents_storage(storage: DocumentsStorage) -> None:
    """Test seam — inject a fake storage/DB client."""
    global _storage
    _storage = storage


def new_document_id() -> str:
    return str(uuid.uuid4())
