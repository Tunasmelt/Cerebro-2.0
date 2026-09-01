"""Stage 3.5 — storage-level tests for SupabaseSealedStorage.seal_document
against a fake httpx transport, same pattern as test_stage_2_5_storage.py.

test_stage_3_3_sealed_api.py and test_stage_3_5_adversarial.py only ever
exercise seal_document through a fake storage seam (_FakeSealedStorage),
so none of them actually run the real atomic-PATCH logic this stage
added to close a live-discovered race condition (sealing a document
whose ingest pipeline was still in flight). These tests hit the real
SupabaseSealedStorage class instead, asserting: the PATCH is sent with
status=eq.ready in its filter; an empty PATCH response (not ready)
short-circuits before any insert/delete call; and a failure partway
through triggers the best-effort status-revert rollback.
"""
import json as _json

import httpx
import pytest

from app.core.sealed_storage import ChunkCiphertext, SealedStorageError, SupabaseSealedStorage


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, patch_matches: bool = True, insert_fails: bool = False):
        self.patch_matches = patch_matches
        self.insert_fails = insert_fails
        self.patch_calls: list[tuple[dict, dict]] = []
        self.insert_calls: list[list[dict]] = []
        self.delete_calls: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if path == "/rest/v1/documents" and request.method == "PATCH":
            body = _json.loads(request.content)
            self.patch_calls.append((params, body))
            if body.get("status") == "sealed":
                if not self.patch_matches:
                    return httpx.Response(200, json=[])
                return httpx.Response(200, json=[{"id": "doc-1", "status": "sealed"}])
            if body.get("status") == "ready":
                # The rollback PATCH.
                return httpx.Response(200, json=[{"id": "doc-1", "status": "ready"}])
            raise AssertionError(f"unexpected PATCH body {body}")

        if path == "/rest/v1/sealed_chunks" and request.method == "POST":
            self.insert_calls.append(_json.loads(request.content))
            if self.insert_fails:
                return httpx.Response(500, text="insert failed")
            return httpx.Response(201, json=[{"id": "sc-1"}])

        if path == "/rest/v1/chunks" and request.method == "DELETE":
            self.delete_calls.append(params)
            return httpx.Response(204)

        raise AssertionError(f"unexpected {request.method} {path}")


def _patch_client(monkeypatch, transport: _FakeTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


@pytest.mark.asyncio
async def test_seal_document_patches_with_status_eq_ready_filter(monkeypatch):
    transport = _FakeTransport()
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    await storage.seal_document(
        user_jwt="t",
        user_id="user-1",
        document_id="doc-1",
        chunks=[ChunkCiphertext(ordinal=0, content_ciphertext_b64="Y3Q=", salt_b64="c2FsdA==", nonce_b64="bm9uY2U=")],
    )

    assert len(transport.patch_calls) == 1
    params, body = transport.patch_calls[0]
    assert params["id"] == "eq.doc-1"
    assert params["status"] == "eq.ready"
    assert body == {"status": "sealed"}
    assert len(transport.insert_calls) == 1
    assert len(transport.delete_calls) == 1


@pytest.mark.asyncio
async def test_seal_document_not_ready_short_circuits_before_any_insert_or_delete(monkeypatch):
    transport = _FakeTransport(patch_matches=False)
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    with pytest.raises(SealedStorageError) as exc_info:
        await storage.seal_document(
            user_jwt="t",
            user_id="user-1",
            document_id="doc-1",
            chunks=[ChunkCiphertext(ordinal=0, content_ciphertext_b64="Y3Q=", salt_b64="c2FsdA==", nonce_b64="bm9uY2U=")],
        )

    assert exc_info.value.code == "not_ready"
    # The whole point: no ciphertext insert, no plaintext delete, if the
    # document wasn't actually ready — the ingest race this stage fixed.
    assert transport.insert_calls == []
    assert transport.delete_calls == []


@pytest.mark.asyncio
async def test_seal_document_reverts_status_on_partial_failure(monkeypatch):
    transport = _FakeTransport(insert_fails=True)
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    with pytest.raises(Exception):
        await storage.seal_document(
            user_jwt="t",
            user_id="user-1",
            document_id="doc-1",
            chunks=[ChunkCiphertext(ordinal=0, content_ciphertext_b64="Y3Q=", salt_b64="c2FsdA==", nonce_b64="bm9uY2U=")],
        )

    # First PATCH flips to sealed, second (rollback) reverts to ready —
    # the document must not be left permanently stuck sealed with no
    # way to retry.
    assert len(transport.patch_calls) == 2
    _, first_body = transport.patch_calls[0]
    _, second_body = transport.patch_calls[1]
    assert first_body == {"status": "sealed"}
    assert second_body == {"status": "ready"}
    # And the plaintext delete must never have run, since the insert
    # (the ciphertext copy) never succeeded.
    assert transport.delete_calls == []
