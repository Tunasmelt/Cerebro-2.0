"""Owned region evidence lookup and lazy layout reindex coordination."""
from __future__ import annotations

import os
from typing import Any

from app.core.http_client import CachedHttpClientMixin


class EvidenceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class SupabaseEvidenceStorage(CachedHttpClientMixin):
    def __init__(self) -> None:
        self._url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, jwt: str) -> dict[str, str]:
        return {"apikey": self._key, "Authorization": f"Bearer {jwt}",
                "Content-Type": "application/json"}

    async def get_evidence(
        self, *, user_jwt: str, chunk_id: str, page_number: int | None = None
    ) -> dict[str, Any]:
        client = self._client()
        response = await client.get(
            f"{self._url}/rest/v1/chunks", headers=self._headers(user_jwt),
            params={"id": f"eq.{chunk_id}", "select": (
                "id,document_id,content,meta,region_id,representation_type,"
                "documents!inner(id,title,status,layout_status),"
                "document_regions(id,region_type,bbox,text_start,text_end,content,"
                "semantic_summary,reading_order,parent_region_id,extraction_source,"
                "document_surfaces!inner(id,surface_index,page_number,kind,width,height,render_path))"
            )},
        )
        rows = response.json()
        if not rows:
            tombstone_response = await client.get(
                f"{self._url}/rest/v1/sealed_evidence_tombstones",
                headers=self._headers(user_jwt),
                params={"chunk_id": f"eq.{chunk_id}", "select": "chunk_id", "limit": "1"},
            )
            if tombstone_response.status_code < 400 and tombstone_response.json():
                raise EvidenceError(
                    "document_sealed", "Exact evidence is unavailable while sealed"
                )
            raise EvidenceError("not_found", "Evidence not found")
        chunk = rows[0]
        document = chunk["documents"]
        if document["status"] == "sealed":
            raise EvidenceError("document_sealed", "Exact evidence is unavailable while sealed")
        region = chunk.get("document_regions")
        if not region:
            return {"chunk_id": chunk_id, "document": document, "legacy": True,
                    "content": chunk["content"], "region": None, "render_url": None}

        context_response = await client.post(
            f"{self._url}/rest/v1/rpc/expand_region_context", headers=self._headers(user_jwt),
            json={"target_region_ids": [region["id"]]},
        )
        context_rows = context_response.json() if context_response.status_code < 400 else []
        context = context_rows[0] if context_rows else {
            "heading_path": [], "nearby": [], "related": []
        }
        source_surface = region.pop("document_surfaces")
        surfaces_response = await client.get(
            f"{self._url}/rest/v1/document_surfaces", headers=self._headers(user_jwt),
            params={"document_id": f"eq.{chunk['document_id']}",
                    "select": "id,surface_index,page_number,kind,width,height,render_path",
                    "order": "surface_index.asc"},
        )
        surfaces = surfaces_response.json() if surfaces_response.status_code < 400 else [source_surface]
        surface = next(
            (item for item in surfaces if page_number is not None and item.get("page_number") == page_number),
            source_surface,
        )
        displayed_region = region if surface["id"] == source_surface["id"] else None
        render_url = None
        if surface.get("render_path"):
            signed = await client.post(
                f"{self._url}/storage/v1/object/sign/evidence/{surface['render_path']}",
                headers=self._headers(user_jwt), json={"expiresIn": 300},
            )
            if signed.status_code < 400:
                value = signed.json().get("signedURL") or signed.json().get("signedUrl")
                render_url = f"{self._url}/storage/v1{value}" if value and value.startswith("/") else value
        return {
            "chunk_id": chunk_id, "document": document, "surface": surface,
            "region": displayed_region, "source_page_number": source_surface.get("page_number"),
            "surfaces": [{"page_number": item.get("page_number")} for item in surfaces],
            "heading_path": context["heading_path"],
            "nearby": context["nearby"], "related": context["related"],
            "render_url": render_url, "legacy": False,
        }

    async def queue_reindex(
        self, *, user_jwt: str, user_id: str, document_id: str
    ) -> str:
        client = self._client()
        response = await client.get(
            f"{self._url}/rest/v1/documents", headers=self._headers(user_jwt),
            params={"id": f"eq.{document_id}", "select": "id,status,layout_status"},
        )
        rows = response.json()
        if not rows:
            raise EvidenceError("not_found", "Document not found")
        document = rows[0]
        if document["status"] == "sealed":
            raise EvidenceError("document_sealed", "Sealed documents cannot be reindexed")
        if document["layout_status"] == "building":
            return "already_queued"
        await client.patch(
            f"{self._url}/rest/v1/documents", headers=self._headers(user_jwt),
            params={"id": f"eq.{document_id}"}, json={"layout_status": "building"},
        )
        await client.patch(
            f"{self._url}/rest/v1/ingest_jobs", headers=self._headers(user_jwt),
            params={"document_id": f"eq.{document_id}"},
            json={"state": "extracting", "checkpoint": {}, "last_error": None},
        )
        return "queued"


_storage = SupabaseEvidenceStorage()


def get_evidence_storage():
    return _storage


def set_evidence_storage(storage) -> None:
    global _storage
    _storage = storage
