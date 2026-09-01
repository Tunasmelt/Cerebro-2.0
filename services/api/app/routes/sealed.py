from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.sealed_storage import ChunkCiphertext, SealedStorageError, get_sealed_storage

router = APIRouter()


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


class SealChunkBody(BaseModel):
    ordinal: int
    content_ciphertext: str  # base64
    salt: str  # base64
    nonce: str  # base64


class SealBody(BaseModel):
    chunks: list[SealChunkBody]


@router.post("/api/v1/documents/{document_id}/seal")
async def seal_document(request: Request, document_id: str, body: SealBody):
    storage = get_sealed_storage()
    try:
        await storage.seal_document(
            user_jwt=request.state.user_jwt,
            user_id=request.state.user["sub"],
            document_id=document_id,
            chunks=[
                ChunkCiphertext(
                    ordinal=c.ordinal,
                    content_ciphertext_b64=c.content_ciphertext,
                    salt_b64=c.salt,
                    nonce_b64=c.nonce,
                )
                for c in body.chunks
            ],
        )
    except SealedStorageError as exc:
        if exc.code == "not_ready":
            return _error(exc.code, exc.message, 409)
        raise
    return JSONResponse({"id": document_id, "status": "sealed"}, status_code=200)


class UnlockBody(BaseModel):
    key: str  # base64 — the Argon2id-derived AES-256-GCM key, this request only


@router.post("/api/v1/documents/{document_id}/unlock")
async def unlock_document(request: Request, document_id: str, body: UnlockBody):
    storage = get_sealed_storage()
    try:
        claim = await storage.create_unlock_claim(
            user_jwt=request.state.user_jwt,
            user_id=request.state.user["sub"],
            document_id=document_id,
            key_b64=body.key,
        )
    except SealedStorageError as exc:
        if exc.code == "not_found":
            return _error(exc.code, exc.message, 404)
        if exc.code == "invalid_key":
            return _error(exc.code, exc.message, 401)
        raise
    return JSONResponse(
        {"claim_id": claim.claim_id, "expires_at": claim.expires_at}, status_code=201
    )


class UnsealBody(BaseModel):
    claim_id: str
    key: str  # base64 — sent again, this request only; never stored server-side


@router.post("/api/v1/documents/{document_id}/unseal")
async def unseal_document(request: Request, document_id: str, body: UnsealBody):
    storage = get_sealed_storage()
    try:
        chunks = await storage.unseal_document(
            user_jwt=request.state.user_jwt,
            user_id=request.state.user["sub"],
            document_id=document_id,
            claim_id=body.claim_id,
            key_b64=body.key,
        )
    except SealedStorageError as exc:
        if exc.code == "claim_not_found":
            return _error(exc.code, exc.message, 404)
        if exc.code == "claim_scope_mismatch":
            return _error(exc.code, exc.message, 403)
        if exc.code == "claim_expired":
            return _error(exc.code, exc.message, 401)
        if exc.code == "invalid_key":
            return _error(exc.code, exc.message, 401)
        raise
    return JSONResponse({"chunks": chunks}, status_code=200)
