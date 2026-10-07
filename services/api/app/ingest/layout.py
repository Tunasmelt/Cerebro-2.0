"""Layout-aware extraction primitives.

The module is deliberately storage-agnostic. It turns one source into ordered
surfaces, typed regions, and optional WebP renders; persistence and semantic
enrichment are separate stages so local extraction remains deterministic.
"""
from __future__ import annotations

import io
import os
import re
import statistics
import tempfile
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image


PDF_RENDER_DPI = 144
PDF_RENDER_SCALE = PDF_RENDER_DPI / 72
MAX_RENDER_DIMENSION = 2000
RENDER_WEBP_QUALITY = 82


class RenderStore(MutableMapping[int, bytes]):
    """Disk-backed renders keep many-page PDFs from accumulating in RAM."""
    def __init__(self) -> None:
        self._directory = tempfile.TemporaryDirectory(prefix="cerebro-evidence-")
        self._keys: set[int] = set()

    @property
    def in_memory_bytes(self) -> int:
        return 0

    def _path(self, key: int) -> str:
        return os.path.join(self._directory.name, f"{key}.webp")

    def __getitem__(self, key: int) -> bytes:
        with open(self._path(key), "rb") as handle:
            return handle.read()

    def __setitem__(self, key: int, value: bytes) -> None:
        with open(self._path(key), "wb") as handle:
            handle.write(value)
        self._keys.add(key)

    def __delitem__(self, key: int) -> None:
        os.remove(self._path(key))
        self._keys.remove(key)

    def __iter__(self) -> Iterator[int]:
        return iter(sorted(self._keys))

    def __len__(self) -> int:
        return len(self._keys)

    def close(self) -> None:
        self._directory.cleanup()
        self._keys.clear()


class LayoutError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class SurfaceKind(StrEnum):
    PDF_PAGE = "pdf_page"
    IMAGE = "image"
    STRUCTURED_TEXT = "structured_text"


class RegionType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    CODE = "code"
    TABLE = "table"
    CHART = "chart"
    IMAGE = "image"
    CAPTION = "caption"
    FOOTNOTE = "footnote"


class RelationType(StrEnum):
    CAPTION_OF = "caption_of"
    REFERENCES = "references"
    CONTINUATION_OF = "continuation_of"


@dataclass(slots=True)
class Surface:
    index: int
    kind: SurfaceKind
    page_number: int | None = None
    width: float | None = None
    height: float | None = None


@dataclass(slots=True)
class Region:
    ordinal: int
    surface_index: int
    region_type: RegionType
    reading_order: int
    content: str = ""
    bbox: tuple[float, float, float, float] | None = None
    text_start: int | None = None
    text_end: int | None = None
    heading_level: int | None = None
    parent_ordinal: int | None = None
    requires_vision: bool = False
    semantic_summary: str | None = None
    extraction_source: str = "local"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RegionRelation:
    source_ordinal: int
    target_ordinal: int
    relation_type: RelationType
    confidence: float | None = None


@dataclass(slots=True)
class LayoutResult:
    surfaces: list[Surface]
    regions: list[Region]
    renders: MutableMapping[int, bytes] = field(default_factory=dict)
    complex_surface_indices: list[int] = field(default_factory=list)
    relations: list[RegionRelation] = field(default_factory=list)


_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_MARKDOWN_LIST = re.compile(r"^\s*(?:[-*+] |\d+[.)] )")
_FIGURE_REFERENCE = re.compile(r"\b(?:figure|fig\.)\s*(\d+)\b", re.I)


def infer_region_relations(regions: list[Region]) -> list[RegionRelation]:
    relations: list[RegionRelation] = []
    figure_targets: dict[str, int] = {}
    visual_types = {RegionType.CHART, RegionType.IMAGE, RegionType.TABLE}
    for index, region in enumerate(regions):
        if region.region_type is not RegionType.CAPTION:
            continue
        target = next(
            (prior for prior in reversed(regions[:index])
             if prior.surface_index == region.surface_index and prior.region_type in visual_types),
            None,
        )
        if target:
            relations.append(RegionRelation(
                region.ordinal, target.ordinal, RelationType.CAPTION_OF, 0.9
            ))
            match = _FIGURE_REFERENCE.search(region.content)
            if match:
                figure_targets[match.group(1)] = target.ordinal
    for region in regions:
        if region.region_type is RegionType.CAPTION:
            continue
        for figure_number in set(_FIGURE_REFERENCE.findall(region.content)):
            target = figure_targets.get(figure_number)
            if target is not None and target != region.ordinal:
                relations.append(RegionRelation(
                    region.ordinal, target, RelationType.REFERENCES, 0.85
                ))
    tables = [region for region in regions if region.region_type is RegionType.TABLE]
    for table in tables:
        previous = next(
            (candidate for candidate in reversed(tables)
             if candidate.surface_index == table.surface_index - 1
             and candidate.ordinal < table.ordinal),
            None,
        )
        if (
            previous and previous.bbox and table.bbox
            and previous.bbox[3] >= 0.75 and table.bbox[1] <= 0.25
        ):
            relations.append(RegionRelation(
                table.ordinal, previous.ordinal, RelationType.CONTINUATION_OF, 0.9
            ))
    return relations


def _iter_text_blocks(source: str) -> list[tuple[int, int, str]]:
    return [
        (match.start(), match.end(), match.group(0))
        for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\s*\Z)", source, re.DOTALL)
    ]


def extract_structured_text(source: str, *, mime: str) -> LayoutResult:
    surface = Surface(index=0, kind=SurfaceKind.STRUCTURED_TEXT)
    regions: list[Region] = []
    heading_stack: list[tuple[int, int]] = []

    for start, end, raw in _iter_text_blocks(source):
        content = raw.strip()
        if not content:
            continue
        region_type = RegionType.PARAGRAPH
        heading_level: int | None = None
        heading = _MARKDOWN_HEADING.match(content) if mime == "text/markdown" else None
        if heading:
            region_type = RegionType.HEADING
            heading_level = len(heading.group(1))
            content = heading.group(2).strip()
        elif mime == "text/markdown" and content.startswith("```"):
            region_type = RegionType.CODE
        elif mime == "text/markdown" and all(
            _MARKDOWN_LIST.match(line) for line in content.splitlines() if line.strip()
        ):
            region_type = RegionType.LIST

        parent_ordinal = heading_stack[-1][1] if heading_stack else None
        ordinal = len(regions)
        if region_type is RegionType.HEADING:
            while heading_stack and heading_stack[-1][0] >= (heading_level or 1):
                heading_stack.pop()
            parent_ordinal = heading_stack[-1][1] if heading_stack else None
            heading_stack.append((heading_level or 1, ordinal))

        regions.append(
            Region(
                ordinal=ordinal,
                surface_index=0,
                region_type=region_type,
                reading_order=ordinal,
                content=content,
                text_start=start,
                text_end=end,
                heading_level=heading_level,
                parent_ordinal=parent_ordinal,
            )
        )
    return LayoutResult(surfaces=[surface], regions=regions)


def extract_image_layout(image_bytes: bytes) -> LayoutResult:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
            render = image.convert("RGB")
            render.thumbnail((MAX_RENDER_DIMENSION, MAX_RENDER_DIMENSION), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            render.save(output, "WEBP", quality=RENDER_WEBP_QUALITY, method=4)
    except (Image.UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise LayoutError("corrupt_image", str(exc)) from exc
    return LayoutResult(
        surfaces=[Surface(0, SurfaceKind.IMAGE, page_number=1, width=width, height=height)],
        regions=[
            Region(
                ordinal=0,
                surface_index=0,
                region_type=RegionType.IMAGE,
                reading_order=0,
                bbox=(0.0, 0.0, 1.0, 1.0),
                requires_vision=True,
            )
        ],
        renders={0: output.getvalue()},
        complex_surface_indices=[0],
    )


def _normalized_bbox(
    x0: float, top: float, x1: float, bottom: float, width: float, height: float
) -> tuple[float, float, float, float]:
    return (
        max(0.0, min(1.0, x0 / width)),
        max(0.0, min(1.0, top / height)),
        max(0.0, min(1.0, x1 / width)),
        max(0.0, min(1.0, bottom / height)),
    )


def _group_words(words: list[dict[str, Any]], page_width: float, page_height: float) -> list[dict]:
    if not words:
        return []
    ordered = sorted(words, key=lambda word: (round(float(word["top"]) / 4), float(word["x0"])))
    lines: list[list[dict[str, Any]]] = []
    for word in ordered:
        if not lines or abs(float(word["top"]) - float(lines[-1][0]["top"])) > 4:
            lines.append([word])
        else:
            lines[-1].append(word)

    sizes = [float(word.get("size") or 0) for word in words if word.get("size")]
    median_size = statistics.median(sizes) if sizes else 0
    blocks: list[dict] = []
    for line in lines:
        line.sort(key=lambda word: float(word["x0"]))
        content = " ".join(str(word["text"]) for word in line).strip()
        if not content:
            continue
        x0 = min(float(word["x0"]) for word in line)
        x1 = max(float(word["x1"]) for word in line)
        top = min(float(word["top"]) for word in line)
        bottom = max(float(word["bottom"]) for word in line)
        line_size = max((float(word.get("size") or 0) for word in line), default=0)
        is_heading = bool(median_size and line_size >= median_size * 1.25 and len(content) <= 160)
        is_caption = bool(re.match(r"^(figure|fig\.|table)\s+\d+", content, re.I))
        is_footnote = top > page_height * 0.86 and line_size and line_size < median_size * 0.9
        region_type = (
            RegionType.CAPTION
            if is_caption
            else RegionType.FOOTNOTE
            if is_footnote
            else RegionType.HEADING
            if is_heading
            else RegionType.PARAGRAPH
        )
        blocks.append(
            {
                "content": content,
                "bbox": _normalized_bbox(x0, top, x1, bottom, page_width, page_height),
                "region_type": region_type,
                "heading_level": 1 if is_heading else None,
            }
        )
    merged: list[dict] = []
    for block in blocks:
        if (
            merged
            and block["region_type"] is RegionType.PARAGRAPH
            and merged[-1]["region_type"] is RegionType.PARAGRAPH
            and abs(block["bbox"][0] - merged[-1]["bbox"][0]) < 0.035
            and block["bbox"][1] - merged[-1]["bbox"][3] < 0.025
        ):
            merged[-1]["content"] += " " + block["content"]
            prior = merged[-1]["bbox"]
            current = block["bbox"]
            merged[-1]["bbox"] = (
                min(prior[0], current[0]), prior[1], max(prior[2], current[2]), current[3]
            )
        else:
            merged.append(block)
    return merged


def _spatial_reading_order(blocks: list[dict]) -> list[dict]:
    """Prefer complete left-column flow before right-column flow."""
    if len(blocks) < 2:
        return blocks
    narrow = [block for block in blocks if block["bbox"][2] - block["bbox"][0] < 0.55]
    has_left = any(block["bbox"][2] <= 0.58 for block in narrow)
    has_right = any(block["bbox"][0] >= 0.42 for block in narrow)
    if not (has_left and has_right):
        return sorted(blocks, key=lambda block: (block["bbox"][1], block["bbox"][0]))
    full_width = [block for block in blocks if block not in narrow]
    left = [block for block in narrow if (block["bbox"][0] + block["bbox"][2]) / 2 < 0.5]
    right = [block for block in narrow if block not in left]
    return (
        sorted(full_width, key=lambda block: block["bbox"][1])
        + sorted(left, key=lambda block: block["bbox"][1])
        + sorted(right, key=lambda block: block["bbox"][1])
    )


def _render_pdf_page(document: pdfium.PdfDocument, index: int) -> bytes:
    page = document[index]
    bitmap = None
    try:
        bitmap = page.render(scale=PDF_RENDER_SCALE)
        image = bitmap.to_pil().convert("RGB")
        image.thumbnail((MAX_RENDER_DIMENSION, MAX_RENDER_DIMENSION), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, "WEBP", quality=RENDER_WEBP_QUALITY, method=4)
        return out.getvalue()
    finally:
        if bitmap is not None:
            bitmap.close()
        page.close()


def extract_pdf_layout(pdf_bytes: bytes) -> LayoutResult:
    surfaces: list[Surface] = []
    regions: list[Region] = []
    renders: MutableMapping[int, bytes] = RenderStore()
    complex_surfaces: list[int] = []
    try:
        render_document = pdfium.PdfDocument(pdf_bytes)
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for index, page in enumerate(pdf.pages):
                    width, height = float(page.width), float(page.height)
                    surfaces.append(
                        Surface(index, SurfaceKind.PDF_PAGE, index + 1, width, height)
                    )
                    renders[index] = _render_pdf_page(render_document, index)
                    words = page.extract_words(extra_attrs=["size", "fontname"])
                    table_blocks: list[dict] = []
                    try:
                        for table in page.find_tables():
                            rows = table.extract() or []
                            content = "\n".join(
                                " | ".join((cell or "").strip() for cell in row) for row in rows
                            ).strip()
                            x0, top, x1, bottom = map(float, table.bbox)
                            table_blocks.append({
                                "content": content,
                                "bbox": _normalized_bbox(x0, top, x1, bottom, width, height),
                                "region_type": RegionType.TABLE,
                                "heading_level": None,
                            })
                    except Exception:
                        table_blocks = []
                    image_blocks = [{
                        "content": "",
                        "bbox": _normalized_bbox(
                            float(image["x0"]), float(image["top"]),
                            float(image["x1"]), float(image["bottom"]), width, height,
                        ),
                        "region_type": RegionType.IMAGE,
                        "heading_level": None,
                    } for image in page.images]
                    blocks = _spatial_reading_order([
                        *_group_words(words, width, height), *table_blocks, *image_blocks
                    ])
                    drawing_count = len(page.images) + len(page.lines) + len(page.rects) + len(page.curves)
                    narrow_text_blocks = [
                        block for block in blocks
                        if block["region_type"] in {RegionType.PARAGRAPH, RegionType.LIST}
                        and block["bbox"][2] - block["bbox"][0] < 0.45
                    ]
                    has_left_column = any(block["bbox"][2] <= 0.58 for block in narrow_text_blocks)
                    has_right_column = any(block["bbox"][0] >= 0.42 for block in narrow_text_blocks)
                    is_complex = (
                        not blocks or bool(page.images) or bool(table_blocks)
                        or drawing_count > 20 or (has_left_column and has_right_column)
                    )
                    if is_complex:
                        complex_surfaces.append(index)
                    if not blocks:
                        blocks = [
                            {
                                "content": "",
                                "bbox": (0.0, 0.0, 1.0, 1.0),
                                "region_type": RegionType.IMAGE,
                                "heading_level": None,
                            }
                        ]
                    parent_heading: int | None = None
                    for reading_order, block in enumerate(blocks):
                        ordinal = len(regions)
                        if block["region_type"] is RegionType.HEADING:
                            parent_heading = ordinal
                        regions.append(
                            Region(
                                ordinal=ordinal,
                                surface_index=index,
                                region_type=block["region_type"],
                                reading_order=reading_order,
                                content=block["content"],
                                bbox=block["bbox"],
                                heading_level=block["heading_level"],
                                parent_ordinal=(
                                    None
                                    if block["region_type"] is RegionType.HEADING
                                    else parent_heading
                                ),
                                requires_vision=(
                                    not block["content"]
                                    or block["region_type"] in {RegionType.IMAGE, RegionType.CHART}
                                ),
                            )
                        )
                    page.flush_cache()
        finally:
            render_document.close()
    except Exception as exc:
        if isinstance(renders, RenderStore):
            renders.close()
        raise LayoutError("corrupt_pdf", str(exc)) from exc
    return LayoutResult(
        surfaces, regions, renders, complex_surfaces, infer_region_relations(regions)
    )
