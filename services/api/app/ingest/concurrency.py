"""Ingest concurrency = 1, non-negotiable per CLAUDE.md ("concurrency=1 on
the ingest worker" — singular: the whole pipeline, not one slot per
stage). A single lock shared across normalize/extract/embed, not a
separate lock per stage — Stage 1.2 originally had its own private lock,
which meant normalizing document A and embedding document B could still
run concurrently. Fixed here, in Stage 1.4, since its exit criteria is
the first to actually test concurrency under load.

Lazily created against the currently-running event loop, and recreated
if that loop changes — an asyncio.Lock() built once (whether at import
time or on first use) binds to whatever loop was running then, and
reusing it from a *different* loop later raises "bound to a different
event loop". uvicorn only ever runs one loop for the process's life, so
production never hits this, but pytest-asyncio gives each test function
its own loop by default — caught by Stage 1.4's own concurrency test,
not assumed away.
"""
import asyncio

_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


def get_ingest_lock() -> asyncio.Lock:
    global _lock, _lock_loop
    current_loop = asyncio.get_event_loop()
    if _lock is None or _lock_loop is not current_loop:
        _lock = asyncio.Lock()
        _lock_loop = current_loop
    return _lock


class _IngestLockProxy:
    """Lets call sites keep writing `async with INGEST_LOCK:` while the
    real Lock is (re)created against whatever loop is currently running."""

    async def __aenter__(self):
        self._lock = get_ingest_lock()
        return await self._lock.__aenter__()

    async def __aexit__(self, *exc_info):
        return await self._lock.__aexit__(*exc_info)


INGEST_LOCK = _IngestLockProxy()
