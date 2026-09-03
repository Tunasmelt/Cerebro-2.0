"""Stage 7.4 — mem_watchdog: RSS logging bracketing each ingest stage.

architecture-and-security.md §3 documented "Log RSS before/after each
ingest stage (`mem_watchdog`)" as an active guardrail; no such logging
ever existed anywhere in the codebase (caught during Phase 7's
pipeline review, same audit that found Stage 7.3's streaming-I/O
claim was also never built). This module is the real thing, so a
future OOM restart on Render's 512MB free tier is traceable to a
specific document and stage instead of a guess.

Stdlib-only (`resource.getrusage`, POSIX) — no new dependency, in
keeping with CLAUDE.md's dependency-hygiene guardrail. `ru_maxrss` is
the process's peak RSS *since process start*, not its RSS at the
instant of the call — it only ever goes up. That's actually the right
semantic for a watchdog: two consecutive readings bracketing a stage
tell you how much that stage pushed the process's all-time high-water
mark, which is exactly what you want to know after an OOM kill. Render
runs Linux, where `ru_maxrss` is in KiB (macOS reports bytes instead —
irrelevant here, but why this isn't used as a portable RSS reader
elsewhere). `resource` doesn't exist on Windows, so local dev logs
nothing instead of crashing — this module is a diagnostic, never load-
bearing for correctness.
"""
import logging
from contextlib import contextmanager
from typing import Iterator

try:
    import resource
except ImportError:  # Windows dev machines — Render (production) is Linux
    resource = None  # type: ignore[assignment]

logger = logging.getLogger("app.ingest.mem_watchdog")


def current_rss_mb() -> float | None:
    """Peak RSS in MB since process start, or None if unavailable
    (non-POSIX platforms only — never raises)."""
    if resource is None:
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


@contextmanager
def track_rss(*, stage: str, document_id: str) -> Iterator[None]:
    """Wrap one ingest stage's call. Logs a `start` line with the RSS
    high-water mark going in and an `end` line with it coming out
    (plus the delta) — always, even if the stage raises, so a crash
    still leaves the `end` reading on record."""
    before = current_rss_mb()
    if before is not None:
        logger.info(
            "mem_watchdog stage=%s document_id=%s phase=start rss_mb=%.1f",
            stage, document_id, before,
        )
    try:
        yield
    finally:
        after = current_rss_mb()
        if after is not None:
            delta = after - before if before is not None else 0.0
            logger.info(
                "mem_watchdog stage=%s document_id=%s phase=end rss_mb=%.1f delta_mb=%.1f",
                stage, document_id, after, delta,
            )
