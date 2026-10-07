"""Versioned 100-question layout/multimodal retrieval evaluation set.

Fixtures are stable logical names so the same corpus can be rendered by local,
staging, or provider-backed evaluation runners without changing question IDs.
"""

SCENARIOS = [
    ("two-column-policy", 2, "paragraph", "cancellation notice"),
    ("nested-headings", 3, "heading", "implementation constraints"),
    ("quarterly-table", 4, "table", "regional revenue"),
    ("revenue-chart", 12, "chart", "quarterly trend"),
    ("captioned-diagram", 6, "caption", "system boundary"),
    ("footnoted-report", 8, "footnote", "methodology caveat"),
    ("scanned-invoice", 1, "paragraph", "invoice total"),
    ("rotated-schedule", 5, "table", "departure time"),
    ("malformed-recovery", 2, "paragraph", "recovered clause"),
    ("hundred-page-manual", 87, "paragraph", "reset procedure"),
    ("product-photo", 1, "image", "serial label"),
    ("large-map-tiles", 1, "image", "northwest marker"),
    ("markdown-guide", None, "code", "configuration example"),
    ("markdown-outline", None, "list", "deployment checklist"),
    ("plain-notes", None, "paragraph", "meeting decision"),
    ("quick-capture", None, "paragraph", "follow-up owner"),
    ("continued-table", 10, "table", "continued totals"),
    ("figure-reference", 7, "chart", "Figure 3 implication"),
    ("visual-only-page", 9, "image", "process sequence"),
    ("mixed-layout", 14, "chart", "forecast comparison"),
]

QUESTION_PATTERNS = [
    "What does the {target} say?",
    "Which page contains the {target}, and what is the answer?",
    "Explain the {region} evidence for the {target}.",
    "Summarize the nearby context around the {target} with a citation.",
    "What unrelated claim about lunar geology does this source prove?",
]

EVALUATION_SET = [
    {
        "id": f"layout-v1-{scenario_index + 1:02d}-{pattern_index + 1}",
        "fixture": fixture,
        "question": pattern.format(target=target, region=region),
        "expected_page": page,
        "expected_region_type": region,
        "answerable": pattern_index < 4,
    }
    for scenario_index, (fixture, page, region, target) in enumerate(SCENARIOS)
    for pattern_index, pattern in enumerate(QUESTION_PATTERNS)
]
