import io

import pikepdf
from PIL import Image

from app.ingest.layout import (
    Region,
    RegionType,
    RelationType,
    SurfaceKind,
    extract_image_layout,
    extract_pdf_layout,
    extract_structured_text,
)
from app.ingest.layout import infer_region_relations


def _pdf_with_text(texts: list[str]) -> bytes:
    pdf = pikepdf.new()
    font = pikepdf.Dictionary(
        Type=pikepdf.Name.Font,
        Subtype=pikepdf.Name.Type1,
        BaseFont=pikepdf.Name.Helvetica,
    )
    for text in texts:
        page = pdf.add_blank_page(page_size=(612, 792))
        page["/Resources"] = pikepdf.Dictionary(
            Font=pikepdf.Dictionary(F1=pdf.make_indirect(font))
        )
        page["/Contents"] = pdf.make_stream(
            f"BT /F1 20 Tf 50 700 Td ({text}) Tj ET".encode()
        )
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def _image_bytes(size=(800, 600)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, "PNG")
    return out.getvalue()


def test_markdown_preserves_heading_hierarchy_and_offsets():
    source = "# Project\n\nIntro paragraph.\n\n## Details\n\n- first\n- second\n"
    layout = extract_structured_text(source, mime="text/markdown")

    assert len(layout.surfaces) == 1
    assert layout.surfaces[0].kind is SurfaceKind.STRUCTURED_TEXT
    assert [r.region_type for r in layout.regions] == [
        RegionType.HEADING,
        RegionType.PARAGRAPH,
        RegionType.HEADING,
        RegionType.LIST,
    ]
    assert layout.regions[2].heading_level == 2
    assert layout.regions[1].parent_ordinal == 0
    assert layout.regions[3].parent_ordinal == 2
    for region in layout.regions:
        assert source[region.text_start : region.text_end].strip()


def test_plain_text_uses_ordered_paragraph_regions_without_fake_pages():
    layout = extract_structured_text("Alpha.\n\nBeta.\n\nGamma.", mime="text/plain")

    assert len(layout.surfaces) == 1
    assert [r.content for r in layout.regions] == ["Alpha.", "Beta.", "Gamma."]
    assert [r.reading_order for r in layout.regions] == [0, 1, 2]
    assert all(r.bbox is None for r in layout.regions)


def test_standalone_image_is_one_spatial_surface_with_normalized_bbox():
    layout = extract_image_layout(_image_bytes((800, 600)))

    assert len(layout.surfaces) == 1
    surface = layout.surfaces[0]
    assert surface.kind is SurfaceKind.IMAGE
    assert (surface.width, surface.height) == (800, 600)
    assert layout.regions[0].region_type is RegionType.IMAGE
    assert layout.regions[0].bbox == (0.0, 0.0, 1.0, 1.0)
    assert layout.regions[0].requires_vision is True


def test_pdf_returns_page_surfaces_text_regions_and_webp_renders():
    layout = extract_pdf_layout(_pdf_with_text(["First page", "Second page"]))

    assert [s.page_number for s in layout.surfaces] == [1, 2]
    assert all(s.kind is SurfaceKind.PDF_PAGE for s in layout.surfaces)
    assert [r.surface_index for r in layout.regions] == [0, 1]
    assert [r.reading_order for r in layout.regions] == [0, 0]
    assert all(r.bbox is not None for r in layout.regions)
    assert all(0 <= coordinate <= 1 for r in layout.regions for coordinate in r.bbox)
    assert set(layout.renders) == {0, 1}
    for render in layout.renders.values():
        image = Image.open(io.BytesIO(render))
        assert image.format == "WEBP"
        assert max(image.size) <= 2000


def test_blank_pdf_page_is_visual_and_marked_for_enrichment():
    layout = extract_pdf_layout(_pdf_with_text([""]))

    assert layout.regions[0].region_type is RegionType.IMAGE
    assert layout.regions[0].requires_vision is True
    assert layout.complex_surface_indices == [0]


def test_caption_is_related_to_nearest_preceding_visual_region():
    regions = [
        Region(0, 0, RegionType.CHART, 0, bbox=(0, 0, 1, .7)),
        Region(1, 0, RegionType.CAPTION, 1, content="Figure 3: Growth", bbox=(0, .7, 1, .8)),
        Region(2, 0, RegionType.PARAGRAPH, 2, content="Figure 3 shows growth."),
    ]
    relations = infer_region_relations(regions)
    assert [(r.source_ordinal, r.target_ordinal, r.relation_type) for r in relations] == [
        (1, 0, RelationType.CAPTION_OF),
        (2, 0, RelationType.REFERENCES),
    ]
