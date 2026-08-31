from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.documents_storage import (
    ALLOWED_MIME_TYPES,
    MAX_UPLOAD_BYTES,
    get_documents_storage,
)
from app.ingest.extract import run_extract_job
from app.ingest.normalize import run_normalize_job

router = APIRouter()


async def _run_ingest_pipeline(*, user_jwt: str, document_id: str) -> None:
    """Chains normalize -> extract in-process, in one background task.
    Each stage module stays independent (per architecture-and-security.md
    §1's "could move to its own service" design intent) — this is the
    only place that knows the pipeline order. Stops early if a stage
    fails; Stage 1.4 owns the real resumable job-state-machine mechanics,
    this is deliberately just sequential chaining for now."""
    normalized = await run_normalize_job(user_jwt=user_jwt, document_id=document_id)
    if not normalized:
        return
    await run_extract_job(user_jwt=user_jwt, document_id=document_id)


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
async def upload_confirm(request: Request, document_id: str, background_tasks: BackgroundTasks):
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

    # Runs in-process, after the response is sent — no separate worker,
    # per CLAUDE.md ("ingest pipeline runs in-process within the web
    # service"). Stage 1.2's normalize concurrency=1 lock means a second
    # confirm's background task queues behind this one rather than
    # running in parallel.
    background_tasks.add_task(
        _run_ingest_pipeline,
        user_jwt=request.state.user_jwt,
        document_id=document_id,
    )

    return JSONResponse(
        {
            "id": confirmed.document_id,
            "state": confirmed.state,
            "size_bytes": confirmed.size_bytes,
        },
        status_code=200,
    )
