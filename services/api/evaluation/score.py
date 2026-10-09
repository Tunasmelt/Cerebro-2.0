"""Provider-agnostic acceptance metric calculation for layout RAG runs."""
from __future__ import annotations

from typing import Any


def score(records: list[dict[str, Any]]) -> dict[str, float]:
    """Score runner output without sending document or model content anywhere.

    Each record carries booleans/numeric counts produced by an external runner;
    this module intentionally never receives prompts, OCR text, or image bytes.
    """
    page_specific = [row for row in records if row.get("expected_page") is not None]
    visual = [row for row in records if row.get("expected_region_type") in {"chart", "image", "table"}]
    return {
        "correct_page_rate": _rate(page_specific, "correct_page"),
        "visual_recall_at_5": _rate(visual, "retrieved_in_top_5"),
        "citation_resolution_rate": _rate(records, "citations_resolved"),
        "answerable_accuracy": _rate(records, "answer_correct"),
    }


def _rate(rows: list[dict[str, Any]], key: str) -> float:
    return sum(bool(row.get(key)) for row in rows) / len(rows) if rows else 0.0
