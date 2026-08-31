"""Stage 1.8 — Langfuse tracing.

get_tracer() is safe to call even without real keys configured —
confirmed live (Stage 1.8 conversation record): with no
LANGFUSE_SECRET_KEY/LANGFUSE_PUBLIC_KEY set, the SDK logs a warning and
returns a disabled client whose span context managers and
get_current_trace_id() become no-ops, never raising. That's what makes
it safe to instrument retrieve.py/chat/stream.py directly with no test
seam — the existing test suite (which sets no Langfuse env vars) gets
no traces, not crashes or noise-free failures.

langfuse-python's own get_client() is already the right singleton
accessor; this module exists only to match the architecture doc's
"core/ ... Langfuse client" line and give one place to import from,
not to add real behavior on top.
"""
from langfuse import get_client

_tracer = None


def get_tracer():
    global _tracer
    if _tracer is None:
        _tracer = get_client()
    return _tracer


def set_tracer(tracer) -> None:
    """Test seam — inject a fake tracer (e.g. to assert span names/order
    deterministically without a real Langfuse project)."""
    global _tracer
    _tracer = tracer
