import json

import pytest

from app.ingest.layout import LayoutResult, Region, RegionType, Surface, SurfaceKind
from app.ingest.layout_enrich import (
    INITIAL_ENRICHMENT_LIMIT,
    merge_vision_regions,
    normalize_gemini_bbox,
    select_surfaces_for_enrichment,
)


def _layout(complex_indices: list[int]) -> LayoutResult:
    return LayoutResult(
        surfaces=[Surface(i, SurfaceKind.PDF_PAGE, i + 1, 100, 200) for i in range(30)],
        regions=[Region(i, i, RegionType.IMAGE, 0, requires_vision=True) for i in range(30)],
        renders={i: b"webp" for i in range(30)},
        complex_surface_indices=complex_indices,
    )


def test_initial_enrichment_is_complexity_ordered_and_bounded():
    layout = _layout(list(range(29, -1, -1)))
    selected = select_surfaces_for_enrichment(layout)

    assert selected == list(range(29, 9, -1))
    assert len(selected) == INITIAL_ENRICHMENT_LIMIT == 20


def test_on_demand_enrichment_is_limited_to_four_unenriched_surfaces():
    layout = _layout([2, 4, 6, 8, 10, 12])
    selected = select_surfaces_for_enrichment(layout, already_enriched={2}, on_demand=True)

    assert selected == [4, 6, 8, 10]


def test_gemini_yxyx_bbox_is_normalized_to_internal_xyxy():
    assert normalize_gemini_bbox([100, 200, 700, 900]) == (0.2, 0.1, 0.9, 0.7)
    assert normalize_gemini_bbox([-50, 0, 1200, 1010]) == (0.0, 0.0, 1.0, 1.0)


def test_valid_vision_output_merges_semantics_without_replacing_local_text():
    local = [
        Region(0, 0, RegionType.PARAGRAPH, 0, content="Reliable embedded text", bbox=(0, 0, 1, .2)),
        Region(1, 0, RegionType.IMAGE, 1, bbox=(0, .2, 1, 1), requires_vision=True),
    ]
    payload = json.dumps({"regions": [
        {"local_ordinal": 0, "type": "paragraph", "bbox": [0, 0, 200, 1000], "content": "hallucinated", "summary": "Introduction"},
        {"local_ordinal": 1, "type": "chart", "bbox": [200, 0, 1000, 1000], "content": "Revenue increases", "summary": "Upward revenue trend"},
    ]})

    merged = merge_vision_regions(local, payload)

    assert merged[0].content == "Reliable embedded text"
    assert merged[0].semantic_summary == "Introduction"
    assert merged[1].region_type is RegionType.CHART
    assert merged[1].content == "Revenue increases"
    assert merged[1].extraction_source == "vision"


@pytest.mark.parametrize("payload", ["not json", "{}", '{"regions":[{"type":"unknown"}]}'])
def test_invalid_vision_output_returns_local_regions_unchanged(payload: str):
    local = [Region(0, 0, RegionType.IMAGE, 0, requires_vision=True)]
    assert merge_vision_regions(local, payload) == local
