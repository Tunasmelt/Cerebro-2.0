"""Persistence and retrieval representations for versioned layouts."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.http_client import CachedHttpClientMixin
from app.ingest.layout import LayoutResult, RegionType


@dataclass(slots=True)
class LayoutRepresentation:
    ordinal: int
    region_ordinal: int
    representation_type: str
    content: str
    meta: dict[str, Any]


def layout_representations(layout: LayoutResult) -> list[LayoutRepresentation]:
    """Create citation-bearing text/caption/visual records for each region."""
    surfaces = {surface.index: surface for surface in layout.surfaces}
    representations: list[LayoutRepresentation] = []
    visual_types = {RegionType.IMAGE, RegionType.CHART, RegionType.TABLE}
    for region in layout.regions:
        surface = surfaces[region.surface_index]
        meta = {
            "surface_index": region.surface_index,
            "page": surface.page_number,
            "region_type": region.region_type.value,
            "bbox": list(region.bbox) if region.bbox else None,
            "heading_level": region.heading_level,
        }
        text = region.content.strip()
        summary = (region.semantic_summary or "").strip()
        if text:
            representations.append(LayoutRepresentation(
                len(representations), region.ordinal, "text", text, meta
            ))
        if summary and summary != text:
            representations.append(LayoutRepresentation(
                len(representations), region.ordinal, "caption", summary, meta
            ))
        if region.region_type in visual_types:
            representations.append(LayoutRepresentation(
                len(representations), region.ordinal, "visual", summary or text, meta
            ))
    return representations


class LayoutPersistError(Exception):
    pass


class SupabaseLayoutStorage(CachedHttpClientMixin):
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {"apikey": self._anon_key, "Authorization": f"Bearer {user_jwt}"}

    async def _post_rows(
        self, table: str, body: list[dict] | dict, *, user_jwt: str,
        prefer: str = "return=representation", params: dict | None = None,
    ) -> list[dict]:
        response = await self._client().post(
            f"{self._supabase_url}/rest/v1/{table}",
            headers={**self._headers(user_jwt), "Content-Type": "application/json", "Prefer": prefer},
            params=params,
            json=body,
        )
        if response.status_code >= 400:
            raise LayoutPersistError(f"{table}: {response.text}")
        return response.json() if response.content else []

    async def persist(
        self, *, user_jwt: str, document_id: str, user_id: str,
        layout: LayoutResult, enriched_surfaces: set[int],
    ) -> str:
        complexity_count = len(layout.complex_surface_indices)
        completeness = (
            1.0 if complexity_count == 0
            else min(1.0, len(enriched_surfaces) / complexity_count)
        )
        generations = await self._post_rows(
            "layout_generations",
            {"document_id": document_id, "user_id": user_id, "version": 2,
             "state": "building", "completeness": completeness,
             "checkpoint": {"enriched_surfaces": sorted(enriched_surfaces)}},
            user_jwt=user_jwt,
        )
        generation_id = generations[0]["id"]
        surface_ids: dict[int, str] = {}
        for surface in layout.surfaces:
            surface_id = str(uuid.uuid4())
            render_path = (
                f"{user_id}/{document_id}/{surface_id}.webp"
                if surface.index in layout.renders else None
            )
            rows = await self._post_rows(
                "document_surfaces",
                {"id": surface_id, "document_id": document_id, "user_id": user_id,
                 "surface_index": surface.index, "kind": surface.kind.value,
                 "page_number": surface.page_number, "width": surface.width,
                 "height": surface.height, "render_path": render_path},
                user_jwt=user_jwt,
                prefer="resolution=merge-duplicates,return=representation",
                params={"on_conflict": "document_id,surface_index"},
            )
            surface_ids[surface.index] = rows[0]["id"]
            if render_path:
                response = await self._client().post(
                    f"{self._supabase_url}/storage/v1/object/evidence/{render_path}",
                    headers={**self._headers(user_jwt), "Content-Type": "image/webp", "x-upsert": "true"},
                    content=layout.renders[surface.index],
                )
                if response.status_code >= 400:
                    raise LayoutPersistError(f"evidence: {response.text}")

        region_ids = {region.ordinal: str(uuid.uuid4()) for region in layout.regions}
        region_rows = [{
            "id": region_ids[region.ordinal], "generation_id": generation_id,
            "surface_id": surface_ids[region.surface_index], "document_id": document_id,
            "user_id": user_id, "ordinal": region.ordinal,
            "region_type": region.region_type.value, "reading_order": region.reading_order,
            "parent_region_id": region_ids.get(region.parent_ordinal),
            "heading_level": region.heading_level,
            "bbox": list(region.bbox) if region.bbox else None,
            "text_start": region.text_start, "text_end": region.text_end,
            "content": region.content, "semantic_summary": region.semantic_summary,
            "extraction_source": region.extraction_source, "meta": region.meta,
        } for region in layout.regions]
        await self._post_rows("document_regions", region_rows, user_jwt=user_jwt, prefer="return=minimal")
        relation_rows = [{
            "document_id": document_id, "user_id": user_id,
            "source_region_id": region_ids[relation.source_ordinal],
            "target_region_id": region_ids[relation.target_ordinal],
            "relation_type": relation.relation_type.value,
            "confidence": relation.confidence,
        } for relation in layout.relations]
        if relation_rows:
            await self._post_rows(
                "region_relations", relation_rows, user_jwt=user_jwt, prefer="return=minimal"
            )

        representations = layout_representations(layout)
        chunk_rows = [{
            "document_id": document_id, "user_id": user_id, "generation_id": generation_id,
            "region_id": region_ids[rep.region_ordinal], "ordinal": rep.ordinal,
            "representation_type": rep.representation_type, "content": rep.content,
            "meta": rep.meta,
        } for rep in representations]
        if chunk_rows:
            await self._post_rows("chunks", chunk_rows, user_jwt=user_jwt, prefer="return=minimal")
        status = "ready" if completeness == 1 else "partial"
        response = await self._client().patch(
            f"{self._supabase_url}/rest/v1/documents",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            params={"id": f"eq.{document_id}"},
            json={"layout_version": 2, "layout_status": status},
        )
        if response.status_code >= 400:
            raise LayoutPersistError(f"documents: {response.text}")
        return generation_id


_storage = SupabaseLayoutStorage()


def get_layout_storage() -> SupabaseLayoutStorage:
    return _storage


def set_layout_storage(storage) -> None:
    global _storage
    _storage = storage
