"""Stage 3.3 — seal/unseal API and unlock claims.

Sealing moves a document's chunks out of `chunks` (plaintext + embedding)
and into `sealed_chunks` (ciphertext only, no embedding column — Stage
3.1) so sealed content structurally cannot enter retrieval. The client
already did the encryption (Stage 3.2's seal.ts, AES-256-GCM via a key
Argon2id-derived from the passphrase) — this module only ever receives
and stores ciphertext for sealing.

Unlocking is different: the passphrase-derived key is never persisted
anywhere (client or server), but per CLAUDE.md's naming-discipline note
it *does* transit to the server per request during an active unlock
session — that's what lets the server prove the key is correct (by
test-decrypting one real sealed_chunks row) before issuing a claim, and
later actually decrypt content for a request. The claim itself carries
no secret; it's a capability, scoped to one document, expiring in 15
minutes, checked against Postgres's own clock server-side so a client
can't extend it by lying about time.
"""
import base64
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException

from app.core.http_client import CachedHttpClientMixin

UNLOCK_CLAIM_TTL = timedelta(minutes=15)


class SealedStorageError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class ChunkCiphertext:
    ordinal: int
    content_ciphertext_b64: str
    salt_b64: str
    nonce_b64: str


@dataclass
class UnlockClaim:
    claim_id: str
    expires_at: str


def is_claim_expired(expires_at: datetime, *, now: datetime | None = None) -> bool:
    """Pure, storage-free — the actual expiry check, unit-testable
    without a database. now() defaults to real time; tests inject a
    fixed instant instead of trying to make a real claim age 15 minutes."""
    current = now if now is not None else datetime.now(timezone.utc)
    return current >= expires_at


def _decrypt(
    key_b64: str, nonce_b64: str, ciphertext_b64: str
) -> bytes:
    key = base64.b64decode(key_b64)
    nonce = base64.b64decode(nonce_b64)
    ciphertext = base64.b64decode(ciphertext_b64)
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise SealedStorageError("invalid_key", "Key failed to decrypt sealed content") from exc


class SealedStorage(Protocol):
    async def seal_document(
        self,
        *,
        user_jwt: str,
        user_id: str,
        document_id: str,
        chunks: list[ChunkCiphertext],
    ) -> None: ...

    async def get_salt(self, *, user_jwt: str, document_id: str) -> str | None: ...

    async def create_unlock_claim(
        self, *, user_jwt: str, user_id: str, document_id: str, key_b64: str
    ) -> UnlockClaim: ...

    async def unseal_document(
        self,
        *,
        user_jwt: str,
        user_id: str,
        document_id: str,
        claim_id: str,
        key_b64: str,
    ) -> list[dict[str, Any]]: ...


class SupabaseSealedStorage(CachedHttpClientMixin):
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {user_jwt}",
            "Content-Type": "application/json",
        }

    async def seal_document(
        self,
        *,
        user_jwt: str,
        user_id: str,
        document_id: str,
        chunks: list[ChunkCiphertext],
    ) -> None:
        rows = [
            {
                "document_id": document_id,
                "user_id": user_id,
                "ordinal": c.ordinal,
                "content_ciphertext": c.content_ciphertext_b64,
                "salt": c.salt_b64,
                "nonce": c.nonce_b64,
            }
            for c in chunks
        ]
        client = self._client()
        # Found live (Stage 3.5 adversarial testing): sealing a
        # document whose background ingest pipeline (normalize ->
        # extract -> embed, kicked off by upload-confirm) was still
        # in flight let that pipeline finish AFTER this function
        # returned, re-writing plaintext + a fresh embedding into
        # `chunks` and overwriting status back to 'ready' — silently
        # un-sealing content that had just been sealed. This single
        # PostgREST PATCH with `status=eq.ready` in the filter is
        # the fix: it atomically flips ready -> sealed at the
        # database level, so it can only ever succeed once ingest
        # has already finished writing every chunk for this
        # document (mark_ready in embed.py is unconditionally the
        # LAST write embed.py makes) — there is no window where
        # ingest can still be mid-flight when this succeeds, and no
        # window where a second concurrent seal attempt could also
        # succeed (only one PATCH call can ever match a row still at
        # status='ready').
        status_resp = await client.patch(
            f"{self._supabase_url}/rest/v1/documents",
            headers={**self._headers(user_jwt), "Prefer": "return=representation"},
            params={"id": f"eq.{document_id}", "status": "eq.ready"},
            json={"status": "sealed"},
        )
        if status_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="seal_status_update_failed")
        if not status_resp.json():
            raise SealedStorageError(
                "not_ready",
                "Document must finish processing (status=ready) before it can be sealed",
            )

        # From here on, status is already 'sealed'. If either write
        # below fails partway, the document must not be left stuck:
        # sealed status with no compensating action would mean the
        # `status=eq.ready` guard above can never match again, so a
        # retry could never re-attempt this seal, and depending on
        # which write failed the document could still hold plaintext
        # in `chunks`, or the caller's ciphertext, or neither. On any
        # failure here, best-effort revert status back to 'ready' so
        # the caller can simply retry sealing.
        try:
            insert_resp = await client.post(
                f"{self._supabase_url}/rest/v1/sealed_chunks",
                headers=self._headers(user_jwt),
                json=rows,
            )
            if insert_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="seal_insert_failed")

            # Sealed content must never remain in the retrieval-path
            # table — delete the plaintext/embedding rows this
            # document had in `chunks` now that the ciphertext copy
            # is stored. Safe to do only now, after the status flip
            # above proved ingest had already finished writing them.
            delete_resp = await client.delete(
                f"{self._supabase_url}/rest/v1/chunks",
                headers=self._headers(user_jwt),
                params={"document_id": f"eq.{document_id}"},
            )
            if delete_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail="seal_chunk_delete_failed")
        except Exception:
            # Best-effort — if this itself fails (network error), the
            # caller must still see the ORIGINAL failure, not this
            # one, so it's swallowed rather than left to replace the
            # exception being propagated below.
            try:
                await client.patch(
                    f"{self._supabase_url}/rest/v1/documents",
                    headers=self._headers(user_jwt),
                    params={"id": f"eq.{document_id}", "status": "eq.sealed"},
                    json={"status": "ready"},
                )
            except Exception:
                pass
            raise

    async def _first_sealed_chunk(
        self, client: httpx.AsyncClient, user_jwt: str, document_id: str
    ) -> dict[str, Any] | None:
        response = await client.get(
            f"{self._supabase_url}/rest/v1/sealed_chunks",
            headers=self._headers(user_jwt),
            params={
                "document_id": f"eq.{document_id}",
                "select": "ordinal,content_ciphertext,salt,nonce",
                "order": "ordinal.asc",
                "limit": 1,
            },
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="sealed_chunk_lookup_failed")
        rows = response.json()
        return rows[0] if rows else None

    async def get_salt(self, *, user_jwt: str, document_id: str) -> str | None:
        """A salt is not secret by design — Argon2id's whole defense
        against precomputed/rainbow-table attacks depends on it being
        unique per document, never on it being hidden — so handing it
        back to the client (the only way the client can re-derive the
        exact key it originally sealed with) doesn't weaken anything.
        None means "not sealed / no rows", same not-found signal every
        other sealed_chunks lookup here already uses.

        Every chunk row of a document now carries the same salt value
        (client-side sealing derives one key per *document*, reused
        with a fresh nonce per chunk — the standard AES-GCM pattern,
        and the only one compatible with unseal_document below actually
        decrypting more than a document's first chunk); any one row's
        salt is as good as any other's, so this just reads the first."""
        client = self._client()
        row = await self._first_sealed_chunk(client, user_jwt, document_id)
        return row["salt"] if row else None

    async def create_unlock_claim(
        self, *, user_jwt: str, user_id: str, document_id: str, key_b64: str
    ) -> UnlockClaim:
        client = self._client()
        probe = await self._first_sealed_chunk(client, user_jwt, document_id)
        if probe is None:
            raise SealedStorageError("not_found", "No sealed content for this document")

        # Raises SealedStorageError("invalid_key", ...) on a wrong
        # key — propagates straight to the caller, no claim issued.
        _decrypt(key_b64, probe["nonce"], probe["content_ciphertext"])

        expires_at = datetime.now(timezone.utc) + UNLOCK_CLAIM_TTL
        claim_resp = await client.post(
            f"{self._supabase_url}/rest/v1/unlock_claims",
            headers={**self._headers(user_jwt), "Prefer": "return=representation"},
            json={
                "document_id": document_id,
                "user_id": user_id,
                "expires_at": expires_at.isoformat(),
            },
        )
        if claim_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="claim_insert_failed")
        claim_row = claim_resp.json()[0]

        return UnlockClaim(claim_id=claim_row["id"], expires_at=claim_row["expires_at"])

    async def _get_claim(
        self, client: httpx.AsyncClient, user_jwt: str, claim_id: str
    ) -> dict[str, Any] | None:
        response = await client.get(
            f"{self._supabase_url}/rest/v1/unlock_claims",
            headers=self._headers(user_jwt),
            params={"id": f"eq.{claim_id}", "select": "id,document_id,expires_at"},
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="claim_lookup_failed")
        rows = response.json()
        return rows[0] if rows else None

    async def unseal_document(
        self,
        *,
        user_jwt: str,
        user_id: str,
        document_id: str,
        claim_id: str,
        key_b64: str,
    ) -> list[dict[str, Any]]:
        client = self._client()
        claim = await self._get_claim(client, user_jwt, claim_id)
        if claim is None:
            # RLS already scopes this to the caller's own claims, so
            # a missing row means "doesn't exist or isn't yours" —
            # same 404-not-403 pattern as documents.py.
            raise SealedStorageError("claim_not_found", "Unlock claim not found")

        # Scope check — a claim issued for one document must never
        # unseal a different one, even the same user's.
        if claim["document_id"] != document_id:
            raise SealedStorageError(
                "claim_scope_mismatch", "Claim is not scoped to this document"
            )

        expires_at = datetime.fromisoformat(claim["expires_at"])
        if is_claim_expired(expires_at):
            raise SealedStorageError("claim_expired", "Unlock claim has expired")

        list_resp = await client.get(
            f"{self._supabase_url}/rest/v1/sealed_chunks",
            headers=self._headers(user_jwt),
            params={
                "document_id": f"eq.{document_id}",
                "select": "ordinal,content_ciphertext,salt,nonce",
                "order": "ordinal.asc",
            },
        )
        if list_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="sealed_chunks_list_failed")
        sealed_rows = list_resp.json()

        # Decrypted plaintext is returned directly in this response and
        # never written to any table — the isolation Stage 3.1 built
        # only holds if this function is the sole place ciphertext ever
        # turns back into plaintext server-side, and only per-request.
        decrypted = []
        for row in sealed_rows:
            plaintext = _decrypt(key_b64, row["nonce"], row["content_ciphertext"])
            decrypted.append({"ordinal": row["ordinal"], "content": plaintext.decode("utf-8")})
        return decrypted


_storage: SealedStorage = SupabaseSealedStorage()


def get_sealed_storage() -> SealedStorage:
    return _storage


def set_sealed_storage(storage: SealedStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage
