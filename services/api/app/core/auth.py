"""Supabase JWT verification.

This project's Supabase instance signs access tokens with an asymmetric
ES256 key (confirmed against the live JWKS endpoint, not assumed), so
verification is done locally against the project's published JWKS rather
than a shared secret or a round-trip to the Auth server on every request —
see https://supabase.com/docs/guides/auth/signing-keys.
"""
import os
from typing import Any

import jwt
from fastapi import HTTPException
from jwt import PyJWKClient

_jwks_client: PyJWKClient | None = None


def _supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"{_supabase_url()}/auth/v1/.well-known/jwks.json"
        # Supabase's own edge cache holds these keys for 10 minutes; matching
        # that here avoids hammering the endpoint without risking a stale
        # key surviving much past Supabase's own revocation window.
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=600)
    return _jwks_client


def set_jwks_client(client: PyJWKClient | None) -> None:
    """Test seam — inject a JWKS client (or reset to None) for a local keypair."""
    global _jwks_client
    _jwks_client = client


def verify_jwt(token: str) -> dict[str, Any]:
    client = get_jwks_client()
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=f"{_supabase_url()}/auth/v1",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid_token") from exc
