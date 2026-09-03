"""Shared, per-instance-cached httpx.AsyncClient — the fix for a real
production memory leak found live: every SupabaseXStorage class (and
CohereRerankClient, GeminiGenerateClient, JinaEmbedClient, …) opened a
brand-new `httpx.AsyncClient()` on every single outbound call. httpx's
own docs warn against exactly this — each construction builds a fresh
SSL context (parsing the full certifi CA bundle) and a fresh connection
pool with no keep-alive reuse across calls. Confirmed live via Render's
metrics: memory climbed linearly and unboundedly (~3MB/min) under a
light, steady request rate with near-idle CPU — not driven by
compute/traffic load, restarting on the 512MB free-tier ceiling every
~1h40m, reproduced identically across independent process restarts.

Fix: every `Supabase*Storage`/API-client class gets ONE lazily-created
httpx.AsyncClient, cached as an instance attribute and reused for the
life of that instance — not a global client threaded through FastAPI's
lifespan. That distinction matters for testing: this codebase's
established test pattern (15 test files) monkeypatches `httpx.AsyncClient`
itself, then constructs a fresh `SupabaseXStorage()` inside the test body
*after* patching — so a per-instance cache created lazily on first real
use picks up the monkeypatch automatically, with zero test-file changes
needed. Every one of these storage classes is itself already a
process-lifetime singleton (`_storage: DocumentsStorage =
SupabaseDocumentsStorage()` at module import time, per get_x_storage()'s
own established pattern throughout this codebase) — so a client cached
on it lives just as long, giving the whole process real HTTP/1.1
keep-alive connection reuse instead of a new TCP+TLS handshake (and a
freshly re-parsed CA bundle) on every request.
"""
import httpx


class CachedHttpClientMixin:
    """Mix in to any class that made per-call `httpx.AsyncClient()`
    instances. `_HTTP_CLIENT_KWARGS` is a class attribute a subclass can
    override (e.g. `{"timeout": 90.0}` for a slow external API) — read
    once, at first client construction, not re-applied per call."""

    _HTTP_CLIENT_KWARGS: dict = {}
    _http_client: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(**self._HTTP_CLIENT_KWARGS)
        return self._http_client
