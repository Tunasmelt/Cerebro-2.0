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

Unlock/unseal pass: get_salt/create_unlock_claim/unseal_document had the
same gap — never exercised against a real fake transport, only through
_FakeSealedStorage at the route level. Added here alongside a real bug
fix found while building the Unlock UI: sealing derived a *different*
key per chunk (a fresh salt on every sealBytes() call), but
unseal_document always decrypted every chunk with one caller-supplied
key — correct only for a single-chunk document. The fix moved to the
client (one key per document, reused with a fresh nonce per chunk — the
standard AES-GCM pattern); test_unseal_document_decrypts_every_chunk_
with_one_shared_key below is what actually proves the backend contract
that fix depends on: one key really does need to decrypt every row.
"""
import base64
import json as _json
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.sealed_storage import ChunkCiphertext, SealedStorageError, SupabaseSealedStorage


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        *,
        patch_matches: bool = True,
        insert_fails: bool = False,
        sealed_chunks: list[dict] | None = None,
        claim: dict | None = None,
        claim_insert_response: dict | None = None,
    ):
        self.patch_matches = patch_matches
        self.insert_fails = insert_fails
        self.sealed_chunks = sealed_chunks or []
        self.claim = claim
        self.claim_insert_response = claim_insert_response
        self.patch_calls: list[tuple[dict, dict]] = []
        self.insert_calls: list[list[dict]] = []
        self.delete_calls: list[dict] = []
        self.claim_insert_calls: list[dict] = []

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

        if path == "/rest/v1/sealed_chunks" and request.method == "GET":
            limit = params.get("limit")
            rows = self.sealed_chunks[: int(limit)] if limit else self.sealed_chunks
            return httpx.Response(200, json=rows)

        if path == "/rest/v1/chunks" and request.method == "DELETE":
            self.delete_calls.append(params)
            return httpx.Response(204)

        if path == "/rest/v1/unlock_claims" and request.method == "POST":
            body = _json.loads(request.content)
            self.claim_insert_calls.append(body)
            return httpx.Response(201, json=[self.claim_insert_response])

        if path == "/rest/v1/unlock_claims" and request.method == "GET":
            return httpx.Response(200, json=[self.claim] if self.claim else [])

        raise AssertionError(f"unexpected {request.method} {path}")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _seal(plaintext: bytes, key: bytes) -> tuple[str, str]:
    """Same helper test_stage_3_3_sealed_api.py's own _seal is, needed
    here too to build realistic sealed_chunks rows for get_salt/
    create_unlock_claim/unseal_document tests."""
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return _b64(nonce), _b64(ciphertext)


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


# --- get_salt -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_salt_returns_the_first_sealed_chunks_salt(monkeypatch):
    transport = _FakeTransport(
        sealed_chunks=[{"ordinal": 0, "content_ciphertext": "Y3Q=", "salt": "c2FsdA==", "nonce": "bm9uY2U="}]
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    salt = await storage.get_salt(user_jwt="t", document_id="doc-1")

    assert salt == "c2FsdA=="


@pytest.mark.asyncio
async def test_get_salt_returns_none_when_nothing_is_sealed(monkeypatch):
    transport = _FakeTransport(sealed_chunks=[])
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    salt = await storage.get_salt(user_jwt="t", document_id="doc-1")

    assert salt is None


# --- create_unlock_claim -------------------------------------------------------


@pytest.mark.asyncio
async def test_create_unlock_claim_verifies_key_against_the_first_chunk_then_issues_a_claim(
    monkeypatch,
):
    key = AESGCM.generate_key(bit_length=256)
    nonce_b64, ciphertext_b64 = _seal(b"first chunk plaintext", key)
    key_b64 = _b64(key)
    expires_at = "2026-01-01T12:15:00+00:00"
    transport = _FakeTransport(
        sealed_chunks=[
            {"ordinal": 0, "content_ciphertext": ciphertext_b64, "salt": "c2FsdA==", "nonce": nonce_b64}
        ],
        claim_insert_response={"id": "claim-1", "expires_at": expires_at},
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    claim = await storage.create_unlock_claim(
        user_jwt="t", user_id="user-1", document_id="doc-1", key_b64=key_b64
    )

    assert claim.claim_id == "claim-1"
    assert claim.expires_at == expires_at
    assert len(transport.claim_insert_calls) == 1
    assert transport.claim_insert_calls[0]["document_id"] == "doc-1"


@pytest.mark.asyncio
async def test_create_unlock_claim_wrong_key_never_issues_a_claim(monkeypatch):
    real_key = AESGCM.generate_key(bit_length=256)
    wrong_key = AESGCM.generate_key(bit_length=256)
    nonce_b64, ciphertext_b64 = _seal(b"first chunk plaintext", real_key)
    transport = _FakeTransport(
        sealed_chunks=[
            {"ordinal": 0, "content_ciphertext": ciphertext_b64, "salt": "c2FsdA==", "nonce": nonce_b64}
        ],
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    with pytest.raises(SealedStorageError) as exc_info:
        await storage.create_unlock_claim(
            user_jwt="t", user_id="user-1", document_id="doc-1", key_b64=_b64(wrong_key)
        )

    assert exc_info.value.code == "invalid_key"
    assert transport.claim_insert_calls == []


@pytest.mark.asyncio
async def test_create_unlock_claim_no_sealed_content_raises_not_found(monkeypatch):
    transport = _FakeTransport(sealed_chunks=[])
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    with pytest.raises(SealedStorageError) as exc_info:
        await storage.create_unlock_claim(
            user_jwt="t", user_id="user-1", document_id="doc-1", key_b64="a2V5"
        )

    assert exc_info.value.code == "not_found"


# --- unseal_document ------------------------------------------------------------


@pytest.mark.asyncio
async def test_unseal_document_decrypts_every_chunk_with_one_shared_key(monkeypatch):
    """The regression proof for the real bug this pass fixed: sealing
    used to derive a *different* key per chunk (a fresh salt per
    sealBytes() call), but this function has only ever accepted one
    caller-supplied key_b64 for the whole document — correct only for a
    single-chunk document, silently broken for any document with more
    than one chunk. The fix moved to the client (one key per document,
    reused with a fresh nonce per chunk); this test proves the backend
    side of that contract actually holds for a real multi-chunk
    document, not just chunk zero."""
    key = AESGCM.generate_key(bit_length=256)
    key_b64 = _b64(key)
    chunk_texts = [b"first chunk of a real document", b"second chunk, different content entirely"]
    sealed_rows = []
    for ordinal, text in enumerate(chunk_texts):
        nonce_b64, ciphertext_b64 = _seal(text, key)
        sealed_rows.append(
            {"ordinal": ordinal, "content_ciphertext": ciphertext_b64, "salt": "c2FsdA==", "nonce": nonce_b64}
        )
    not_expired = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    transport = _FakeTransport(
        sealed_chunks=sealed_rows,
        claim={"id": "claim-1", "document_id": "doc-1", "expires_at": not_expired},
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    result = await storage.unseal_document(
        user_jwt="t", user_id="user-1", document_id="doc-1", claim_id="claim-1", key_b64=key_b64
    )

    assert result == [
        {"ordinal": 0, "content": chunk_texts[0].decode()},
        {"ordinal": 1, "content": chunk_texts[1].decode()},
    ]


@pytest.mark.asyncio
async def test_unseal_document_claim_not_found(monkeypatch):
    transport = _FakeTransport(claim=None)
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    with pytest.raises(SealedStorageError) as exc_info:
        await storage.unseal_document(
            user_jwt="t", user_id="user-1", document_id="doc-1", claim_id="does-not-exist", key_b64="a2V5"
        )

    assert exc_info.value.code == "claim_not_found"


@pytest.mark.asyncio
async def test_unseal_document_claim_scoped_to_a_different_document_is_rejected(monkeypatch):
    not_expired = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    transport = _FakeTransport(
        claim={"id": "claim-1", "document_id": "some-other-doc", "expires_at": not_expired}
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    with pytest.raises(SealedStorageError) as exc_info:
        await storage.unseal_document(
            user_jwt="t", user_id="user-1", document_id="doc-1", claim_id="claim-1", key_b64="a2V5"
        )

    assert exc_info.value.code == "claim_scope_mismatch"


@pytest.mark.asyncio
async def test_unseal_document_expired_claim_is_rejected(monkeypatch):
    already_expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    transport = _FakeTransport(
        claim={"id": "claim-1", "document_id": "doc-1", "expires_at": already_expired}
    )
    _patch_client(monkeypatch, transport)
    storage = SupabaseSealedStorage()

    with pytest.raises(SealedStorageError) as exc_info:
        await storage.unseal_document(
            user_jwt="t", user_id="user-1", document_id="doc-1", claim_id="claim-1", key_b64="a2V5"
        )

    assert exc_info.value.code == "claim_expired"
