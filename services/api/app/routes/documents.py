from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.documents_storage import (
    ALLOWED_MIME_TYPES,
    MAX_UPLOAD_BYTES,
    get_documents_storage,
    new_document_id,
)

router = APIRouter()


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


@router.post("/api/v1/documents")
async def upload_document(request: Request, file: UploadFile):
    if file.content_type not in ALLOWED_MIME_TYPES:
        return _error(
            "unsupported_mime_type",
            f"'{file.content_type}' is not a supported file type",
            400,
        )

    content = await file.read()
    # Defense in depth — the Next.js proxy is the guaranteed enforcement
    # point (architecture-and-security.md §3), this just makes sure a
    # request that somehow bypasses the proxy still can't reach storage.
    if len(content) > MAX_UPLOAD_BYTES:
        return _error("file_too_large", "File exceeds the 50MB upload limit", 413)

    user_id = request.state.user["sub"]
    user_jwt = request.state.user_jwt
    document_id = new_document_id()
    ext = ALLOWED_MIME_TYPES[file.content_type]
    storage = get_documents_storage()

    original_storage_path = await storage.upload_original(
        user_jwt=user_jwt,
        user_id=user_id,
        document_id=document_id,
        ext=ext,
        content=content,
        mime=file.content_type,
    )
    document = await storage.insert_document(
        user_jwt=user_jwt,
        user_id=user_id,
        document_id=document_id,
        title=file.filename or "untitled",
        mime=file.content_type,
        size_bytes=len(content),
        original_storage_path=original_storage_path,
    )

    return JSONResponse(
        {
            "id": document.id,
            "title": document.title,
            "mime": document.mime,
            "size_bytes": document.size_bytes,
            "original_storage_path": document.original_storage_path,
            "status": document.status,
        },
        status_code=201,
    )
