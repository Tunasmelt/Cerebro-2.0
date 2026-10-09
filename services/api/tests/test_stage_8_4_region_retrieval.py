from app.retrieve.region_context import (
    deduplicate_by_region,
    explicit_page_number,
    page_boost,
    serialize_evidence,
)


def _row(chunk_id: str, *, region: str | None, page: int, kind="text"):
    return {
        "id": chunk_id, "document_id": "doc", "content": f"content-{chunk_id}",
        "meta": {"region_id": region, "page": page, "representation_type": kind,
                 "region_type": "chart", "heading_path": ["Results"]},
    }


def test_page_reference_detection_and_boost_are_explicit_only():
    assert explicit_page_number("What does the chart on page 12 imply?") == 12
    assert explicit_page_number("compare 12 charts") is None
    rows = [_row("a", region="ra", page=4), _row("b", region="rb", page=12)]
    assert [r["id"] for r in page_boost(rows, 12)] == ["b", "a"]


def test_deduplication_uses_region_identity_but_keeps_legacy_chunks():
    rows = [
        _row("visual", region="same", page=1, kind="visual"),
        _row("caption", region="same", page=1, kind="caption"),
        _row("legacy-a", region=None, page=1),
        _row("legacy-b", region=None, page=1),
    ]
    assert [r["id"] for r in deduplicate_by_region(rows)] == ["visual", "legacy-a", "legacy-b"]


def test_rerank_serialization_contains_layout_metadata():
    row = _row("x", region="r", page=7)
    row["document_title"] = "Quarterly report"
    text = serialize_evidence(row)
    assert "Quarterly report" in text
    assert "Results" in text
    assert "Page: 7" in text
    assert "Region: chart" in text
    assert "content-x" in text
