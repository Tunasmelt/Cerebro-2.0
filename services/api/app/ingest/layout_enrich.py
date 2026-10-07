"""Best-effort semantic enrichment for locally extracted page regions."""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import replace

from app.chat import generate as generate_module
from app.ingest.layout import LayoutResult, Region, RegionType

logger = logging.getLogger(__name__)

INITIAL_ENRICHMENT_LIMIT = 20
ON_DEMAND_ENRICHMENT_LIMIT = 4

_VISION_INSTRUCTION = """Analyze one rendered document page. Return ONLY JSON:
{"regions":[{"local_ordinal":0,"type":"chart","bbox":[ymin,xmin,ymax,xmax],
"content":"verified visible text or concise description","summary":"semantic meaning"}]}
Bounding boxes use integers from 0 to 1000. Valid types are heading, paragraph,
list, code, table, chart, image, caption, footnote. Use local_ordinal when a
candidate corresponds to a supplied local region. Never rewrite reliable text."""


def select_surfaces_for_enrichment(
    layout: LayoutResult,
    *,
    already_enriched: set[int] | None = None,
    on_demand: bool = False,
) -> list[int]:
    """Select complex pages deterministically while enforcing model budgets."""
    seen = already_enriched or set()
    limit = ON_DEMAND_ENRICHMENT_LIMIT if on_demand else INITIAL_ENRICHMENT_LIMIT
    return [index for index in layout.complex_surface_indices if index not in seen][:limit]


def normalize_gemini_bbox(values: list[float | int]) -> tuple[float, float, float, float]:
    if len(values) != 4:
        raise ValueError("bbox must have four coordinates")
    ymin, xmin, ymax, xmax = (max(0.0, min(1000.0, float(value))) for value in values)
    x0, x1 = sorted((xmin / 1000, xmax / 1000))
    y0, y1 = sorted((ymin / 1000, ymax / 1000))
    return x0, y0, x1, y1


def _json_payload(raw: str) -> dict:
    value = raw.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0]
    parsed = json.loads(value)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("regions"), list):
        raise ValueError("regions array missing")
    return parsed


def merge_vision_regions(local_regions: list[Region], raw_payload: str) -> list[Region]:
    """Validate and merge vision output, retaining trustworthy embedded text."""
    try:
        payload = _json_payload(raw_payload)
        replacements: dict[int, Region] = {}
        local_by_ordinal = {region.ordinal: region for region in local_regions}
        for candidate in payload["regions"]:
            if not isinstance(candidate, dict):
                raise ValueError("invalid region")
            ordinal = int(candidate["local_ordinal"])
            local = local_by_ordinal[ordinal]
            region_type = RegionType(candidate["type"])
            bbox = normalize_gemini_bbox(candidate["bbox"])
            generated_content = str(candidate.get("content") or "").strip()
            summary = str(candidate.get("summary") or "").strip() or None
            reliable_local_text = bool(local.content.strip())
            replacements[ordinal] = replace(
                local,
                region_type=region_type,
                bbox=bbox,
                content=local.content if reliable_local_text else generated_content,
                semantic_summary=summary,
                requires_vision=False,
                extraction_source="merged" if reliable_local_text else "vision",
            )
        if not replacements:
            raise ValueError("empty regions")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return local_regions
    return [replacements.get(region.ordinal, region) for region in local_regions]


def _extract_model_text(interaction: dict) -> str:
    return "".join(
        block.get("text", "")
        for step in interaction.get("steps", [])
        if step.get("type") == "model_output"
        for block in step.get("content", [])
        if block.get("type") == "text"
    ).strip()


async def enrich_layout(
    layout: LayoutResult,
    *,
    already_enriched: set[int] | None = None,
    on_demand: bool = False,
) -> tuple[LayoutResult, set[int]]:
    """Enrich selected renders sequentially; model failures preserve local output."""
    enriched = set(already_enriched or set())
    for surface_index in select_surfaces_for_enrichment(
        layout, already_enriched=enriched, on_demand=on_demand
    ):
        render = layout.renders.get(surface_index)
        if not render:
            continue
        page_regions = [r for r in layout.regions if r.surface_index == surface_index]
        geometry = [
            {"local_ordinal": r.ordinal, "type": r.region_type.value, "bbox": r.bbox,
             "content": r.content}
            for r in page_regions
        ]
        try:
            interaction = await generate_module.run_interaction(
                system_instruction=_VISION_INSTRUCTION,
                input_data=[
                    {"type": "text", "text": json.dumps({"local_regions": geometry})},
                    {"type": "image", "data": base64.b64encode(render).decode(),
                     "mime_type": "image/webp"},
                ],
            )
            merged = merge_vision_regions(page_regions, _extract_model_text(interaction))
            if merged != page_regions:
                by_ordinal = {region.ordinal: region for region in merged}
                layout.regions = [by_ordinal.get(region.ordinal, region) for region in layout.regions]
                enriched.add(surface_index)
        except Exception:
            logger.exception("Layout enrichment failed for surface %s", surface_index)
    return layout, enriched
