"""Regression test for a real production memory leak: every
Supabase*Storage class (and CohereRerankClient, GeminiGenerateClient,
JinaEmbedClient, …) used to open a brand-new httpx.AsyncClient() on
every single outbound call — no connection/SSL-context reuse. Confirmed
live via Render's metrics: memory climbed linearly and unboundedly
(~3MB/min) under a light, steady request rate with near-idle CPU,
restarting on the 512MB free-tier ceiling every ~1h40m, reproduced
identically across independent process restarts. See
app/core/http_client.py's module docstring for the full writeup.

This file tests the shared mixin in isolation (not any one storage
class) — every Supabase*Storage class's own test file already proves
its httpx calls still work correctly against a fake transport (that's
what confirms this fix didn't break the established fake-httpx-
transport test pattern used throughout this codebase); this file proves
the actual caching behavior the fix is supposed to add.
"""
import httpx
import pytest

from app.core.http_client import CachedHttpClientMixin


class _FakeStorage(CachedHttpClientMixin):
    pass


class _FakeStorageWithTimeout(CachedHttpClientMixin):
    _HTTP_CLIENT_KWARGS = {"timeout": 90.0}


def test_client_is_created_lazily_not_at_construction():
    storage = _FakeStorage()
    assert storage._http_client is None


def test_repeated_calls_reuse_the_same_client_instance():
    """The whole point of the fix: N calls must reuse one client, not
    construct N of them."""
    storage = _FakeStorage()
    first = storage._client()
    second = storage._client()
    third = storage._client()
    assert first is second is third


def test_different_instances_get_different_clients():
    """Caching is per-instance, not a hidden process-wide global — this
    is what keeps every existing fake-httpx-transport test working
    unmodified: each test constructs its own fresh SupabaseXStorage()
    after monkeypatching httpx.AsyncClient, so it must get its own,
    freshly-constructed (and therefore correctly-patched) client, never
    one left over from an earlier test's instance."""
    a = _FakeStorage()
    b = _FakeStorage()
    assert a._client() is not b._client()


def test_http_client_kwargs_applied_to_the_constructed_client():
    storage = _FakeStorageWithTimeout()
    client = storage._client()
    assert client.timeout.read == 90.0


def test_default_http_client_kwargs_is_empty():
    storage = _FakeStorage()
    client = storage._client()
    # httpx's own default timeout, not the 90s override —
    # confirms _HTTP_CLIENT_KWARGS isn't leaking across subclasses via
    # a shared mutable default.
    assert client.timeout.read != 90.0


@pytest.mark.asyncio
async def test_monkeypatched_httpx_asyncclient_is_picked_up_on_first_use(monkeypatch):
    """The exact mechanism every existing fake-httpx-transport test
    relies on: monkeypatch.setattr(httpx, "AsyncClient", fake) BEFORE a
    fresh instance's first `_client()` call must still take effect,
    since the cache is empty (None) until then."""

    class _FakeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200, json={"ok": True})

    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = _FakeTransport()
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    storage = _FakeStorage()
    client = storage._client()
    response = await client.get("https://example.invalid/anything")
    assert response.json() == {"ok": True}
