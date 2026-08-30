from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.documents_storage import (
    ALLOWED_MIME_TYPES,
    MAX_UPLOAD_BYTES,
    get_documents_storage,
)

router = APIRouter()


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


class UploadInitBody(BaseModel):
    filename: str
    mime: str
    size_bytes: int


@router.post("/api/v1/documents/upload-init")
async def upload_init(request: Request, body: UploadInitBody):
    if body.mime not in ALLOWED_MIME_TYPES:
        return _error(
            "unsupported_mime_type",
            f"'{body.mime}' is not a supported file type",
            400,
        )
    # Fast feedback only — never the enforcement boundary (that's Supabase
    # Storage's bucket-level file_size_limit, checked for real at
    # upload-confirm against the actual uploaded bytes).
    if body.size_bytes > MAX_UPLOAD_BYTES:
        return _error("file_too_large", "File exceeds the 50MB upload limit", 413)

    storage = get_documents_storage()
    signed = await storage.authorize(
        user_jwt=request.state.user_jwt,
        user_id=request.state.user["sub"],
        title=body.filename,
        mime=body.mime,
    )
    return JSONResponse(
        {"id": signed.document_id, "upload_url": signed.upload_url},
        status_code=201,
    )


@router.post("/api/v1/documents/{document_id}/upload-confirm")
async def upload_confirm(request: Request, document_id: str):
    storage = get_documents_storage()
    try:
        confirmed = await storage.confirm(
            user_jwt=request.state.user_jwt,
            user_id=request.state.user["sub"],
            document_id=document_id,
        )
    except HTTPException as exc:
        if exc.detail == "document_not_found":
            return _error("not_found", "Document not found", 404)
        if exc.detail == "upload_not_found":
            return _error(
                "upload_not_found",
                "No uploaded object found for this document yet",
                422,
            )
        if exc.detail == "file_too_large":
            return _error("file_too_large", "File exceeds the 50MB upload limit", 413)
        raise

    return JSONResponse(
        {
            "id": confirmed.document_id,
            "state": confirmed.state,
            "size_bytes": confirmed.size_bytes,
        },
        status_code=200,
    )
