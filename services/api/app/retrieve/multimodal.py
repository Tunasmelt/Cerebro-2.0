"""Bounded multimodal generation payload assembly."""
from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable

from app.retrieve.retrieve import RetrievedChunk

MAX_VISUAL_CROPS = 4
MAX_VISUAL_BYTES = 6 * 1024 * 1024
VISUAL_REGION_TYPES = {"chart", "image", "table"}


async def build_multimodal_input(
    query: str,
    chunks: list[RetrievedChunk],
    load_region: Callable[[str], Awaitable[tuple[bytes, str] | None]],
) -> list[dict]:
    blocks: list[dict] = [{"type": "text", "text": query}]
    loaded_count = 0
    loaded_bytes = 0
    seen_regions: set[str] = set()
    for chunk in chunks:
        meta = chunk.meta or {}
        region_id = meta.get("region_id")
        if (
            not region_id
            or region_id in seen_regions
            or meta.get("region_type") not in VISUAL_REGION_TYPES
            or loaded_count >= MAX_VISUAL_CROPS
        ):
            continue
        loaded = await load_region(region_id)
        seen_regions.add(region_id)
        if not loaded:
            continue
        image_bytes, mime_type = loaded
        encoded_size = 4 * ((len(image_bytes) + 2) // 3)
        if loaded_bytes + encoded_size > MAX_VISUAL_BYTES:
            break
        blocks.append({
            "type": "text",
            "text": (
                f"Visual evidence [[chunk:{chunk.chunk_id}]] — "
                f"page {meta.get('page') or 'n/a'}, {meta.get('region_type')}."
            ),
        })
        blocks.append({
            "type": "image",
            "data": base64.b64encode(image_bytes).decode(),
            "mime_type": mime_type,
        })
        loaded_count += 1
        loaded_bytes += encoded_size
    return blocks
