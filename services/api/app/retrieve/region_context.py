"""Pure ranking helpers for layout-aware evidence."""
from __future__ import annotations

import re
from typing import Any

_PAGE_REFERENCE = re.compile(r"\b(?:page|p\.)\s*(\d{1,6})\b", re.I)


def explicit_page_number(query: str) -> int | None:
    match = _PAGE_REFERENCE.search(query)
    return int(match.group(1)) if match else None


def page_boost(rows: list[dict[str, Any]], page_number: int | None) -> list[dict[str, Any]]:
    if page_number is None:
        return rows
    return sorted(
        rows,
        key=lambda row: 0 if row.get("meta", {}).get("page") == page_number else 1,
    )


def deduplicate_by_region(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        region_id = row.get("meta", {}).get("region_id") or row.get("region_id")
        if region_id and region_id in seen:
            continue
        if region_id:
            seen.add(region_id)
        result.append(row)
    return result


def serialize_evidence(row: dict[str, Any]) -> str:
    meta = row.get("meta") or {}
    heading_path = " > ".join(meta.get("heading_path") or [])
    parts = [
        f"Document: {row.get('document_title') or meta.get('document_title') or 'Untitled'}",
        f"Heading: {heading_path or 'Root'}",
        f"Page: {meta.get('page') or 'n/a'}",
        f"Region: {meta.get('region_type') or 'text'}",
        f"Content: {row.get('content') or meta.get('caption') or ''}",
    ]
    return "\n".join(parts)
