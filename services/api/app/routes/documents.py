from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.documents_storage import (
    ALLOWED_MIME_TYPES,
    MAX_UPLOAD_BYTES,
    get_documents_storage,
)
from app.graph.cluster import place_new_document
from app.ingest.embed import RetryError, check_retry_eligible, run_embed_job
from app.ingest.extract import run_extract_job
from app.ingest.normalize import run_normalize_job

router = APIRouter()


async def _embed_then_place(*, user_jwt: str, user_id: str, document_id: str) -> None:
    """Stage 2.5 — a successful embed is followed by nearest-centroid
    placement into the graph (see graph/cluster.py's
    place_new_document), not a manual /graph/recluster call. Only on
    success: a failed embed has nothing to place, and check_retry_eligible
    already scopes retries to embed-stage failures specifically, so
    retry-ingest reaches this same path once it actually succeeds."""
    embedded = await run_embed_job(user_jwt=user_jwt, document_id=document_id)
    if embedded:
        await place_new_document(user_jwt=user_jwt, user_id=user_id, document_id=document_id)


async def _run_ingest_pipeline(*, user_jwt: str, user_id: str, document_id: str) -> None:
    """Chains normalize -> extract -> embed in-process, in one background
    task. Each stage module stays independent (per
    architecture-and-security.md §1's "could move to its own service"
    design intent) — this is the only place that knows the pipeline
    order. Stops early if a stage fails; each stage's own checkpoint
    (embed's ingest_jobs.checkpoint) is what actually makes a crash mid-
    pipeline resumable, not this wrapper."""
    normalized = await run_normalize_job(user_jwt=user_jwt, document_id=document_id)
    if not normalized:
        return
    extracted = await run_extract_job(user_jwt=user_jwt, document_id=document_id)
    if not extracted:
        return
    await _embed_then_place(user_jwt=user_jwt, user_id=user_id, document_id=document_id)


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
        user_id=request.state.user["sub"],
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


@router.get("/api/v1/documents")
async def list_documents(request: Request):
    storage = get_documents_storage()
    documents = await storage.list_documents(
        user_jwt=request.state.user_jwt, user_id=request.state.user["sub"]
    )
    return JSONResponse({"documents": documents}, status_code=200)


@router.post("/api/v1/documents/{document_id}/retry-ingest")
async def retry_ingest(request: Request, document_id: str, background_tasks: BackgroundTasks):
    """Retries a document whose embed stage failed. Scoped to embed-stage
    failures only — see check_retry_eligible's docstring for why
    normalize/extract failures aren't auto-retried here yet."""
    try:
        await check_retry_eligible(
            user_jwt=request.state.user_jwt, document_id=document_id
        )
    except RetryError as exc:
        status_code = 404 if exc.code == "not_found" else 409
        return _error(exc.code, exc.message, status_code)

    background_tasks.add_task(
        _embed_then_place,
        user_jwt=request.state.user_jwt,
        user_id=request.state.user["sub"],
        document_id=document_id,
    )
    return JSONResponse({"id": document_id, "state": "embedding"}, status_code=202)
