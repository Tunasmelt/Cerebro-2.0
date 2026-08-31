"""Per-user, per-route-class rate limiting.

Limits are the ones documented in architecture-and-security.md §4. Real
chat/upload/seal/graph endpoints don't exist yet (Phase 1/3) — this
classifies against the *documented future paths* from api-documentation.md
so real handlers inherit the right limit automatically once built, instead
of needing every new route to remember to opt in.

That plan broke silently once: this module originally matched
`POST /api/v1/documents` for the "upload" class, guessed before Stage
1.1 built the real upload flow — which ended up at
`POST /api/v1/documents/upload-init` instead, a path that never matched
the guess. The mismatch fell through to the "general" class (100/min)
and sat undetected until a live Phase 0 audit actually burst-tested
production and found 15 upload-init calls succeeding with no 429 where
10/hour should have kicked in. Fixed here; see
tests/test_stage_0_6_rate_limit.py for the regression test. Lesson:
this file's "classify against the documented future path" approach
needs to be re-checked against the real route the moment it's built,
not just relied on to already line up.

In-memory sliding-window log, not Redis: this project's stack has no
external cache/queue, Render's free tier runs a single instance/single
uvicorn worker (per CLAUDE.md), so per-process state is genuinely
per-deployment state — no cross-instance drift to worry about. Revisit this
if the service ever scales beyond one instance.
"""
import re
import threading
import time
from collections import defaultdict, deque
from typing import Callable

# (limit, window_seconds), per architecture-and-security.md §4.
LIMITS: dict[str, tuple[int, int]] = {
    "chat": (20, 60),
    "upload": (10, 3600),
    "seal_unseal": (5, 3600),
    "graph": (60, 60),
    "general": (100, 60),
}

_SEAL_UNSEAL_RE = re.compile(r"^/api/v1/documents/[^/]+/(seal|unseal)$")


def classify_route(path: str, method: str) -> str | None:
    if not path.startswith("/api/v1/"):
        return None
    if path.startswith("/api/v1/chat/"):
        return "chat"
    if _SEAL_UNSEAL_RE.match(path):
        return "seal_unseal"
    if path == "/api/v1/documents/upload-init" and method == "POST":
        return "upload"
    if path.startswith("/api/v1/graph"):
        return "graph"
    return "general"


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, user_id: str, route_class: str) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds). Records the hit if allowed."""
        limit, window = LIMITS[route_class]
        now = self._clock()
        key = (user_id, route_class)
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= limit:
                return False, window - (now - hits[0])
            hits.append(now)
            return True, 0.0


_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter


def set_rate_limiter(limiter: RateLimiter) -> None:
    """Test seam — inject a RateLimiter with a fake clock."""
    global _rate_limiter
    _rate_limiter = limiter
