from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.chat.action_items import extract_action_items
from app.core.documents_storage import (
    ALLOWED_MIME_TYPES,
    MAX_CAPTURE_CHARS,
    MAX_UPLOAD_BYTES,
    DocumentsStorageError,
    get_documents_storage,
)
from app.graph.cluster import place_new_document
from app.ingest.embed import RetryError, check_retry_eligible, run_embed_job
from app.ingest.extract import run_extract_job
from app.ingest.mem_watchdog import track_rss
from app.ingest.normalize import run_normalize_job

router = APIRouter()


async def _embed_then_place(*, user_jwt: str, user_id: str, document_id: str) -> None:
    """Stage 2.5 — a successful embed is followed by nearest-centroid
    placement into the graph (see graph/cluster.py's
    place_new_document), not a manual /graph/recluster call. Only on
    success: a failed embed has nothing to place, and check_retry_eligible
    already scopes retries to embed-stage failures specifically, so
    retry-ingest reaches this same path once it actually succeeds."""
    with track_rss(stage="embed", document_id=document_id):
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
    pipeline resumable, not this wrapper. Stage 7.4: each stage call is
    bracketed by mem_watchdog's track_rss, so an OOM restart is
    traceable to a specific document and stage from the logs alone."""
    with track_rss(stage="normalize", document_id=document_id):
        normalized = await run_normalize_job(user_jwt=user_jwt, document_id=document_id)
    if not normalized:
        return
    with track_rss(stage="extract", document_id=document_id):
        extracted = await run_extract_job(user_jwt=user_jwt, document_id=document_id)
    if not extracted:
        return
    await _embed_then_place(user_jwt=user_jwt, user_id=user_id, document_id=document_id)


async def _run_capture_pipeline(*, user_jwt: str, user_id: str, document_id: str) -> None:
    """Stage 5.5 — extract -> embed only, deliberately skipping
    run_normalize_job entirely: a captured thought has no file to
    normalize (see documents_storage.py's create_capture and
    extract.py's source == "capture" branch)."""
    with track_rss(stage="extract", document_id=document_id):
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


class CaptureBody(BaseModel):
    text: str
    title: str | None = None


@router.post("/api/v1/documents/capture")
async def capture(request: Request, body: CaptureBody, background_tasks: BackgroundTasks):
    """Stage 5.5 — quick capture: a persistent, always-available way to
    get a thought into the vault without going through the file-upload
    flow. Feeds the same extract -> embed pipeline every uploaded
    document does (_run_capture_pipeline), just skipping normalize —
    see documents_storage.py's create_capture for why."""
    text = body.text.strip()
    if not text:
        return _error("empty_text", "Capture text cannot be empty", 422)
    if len(text) > MAX_CAPTURE_CHARS:
        return _error(
            "text_too_long", f"Capture text exceeds {MAX_CAPTURE_CHARS} characters", 413
        )

    title = (body.title or "").strip() or (
        text[:60] + "…" if len(text) > 60 else text
    )

    storage = get_documents_storage()
    document_id = await storage.create_capture(
        user_jwt=request.state.user_jwt,
        user_id=request.state.user["sub"],
        title=title,
        text=text,
    )

    background_tasks.add_task(
        _run_capture_pipeline,
        user_jwt=request.state.user_jwt,
        user_id=request.state.user["sub"],
        document_id=document_id,
    )

    return JSONResponse({"id": document_id, "state": "extracting"}, status_code=201)


@router.get("/api/v1/documents")
async def list_documents(request: Request):
    storage = get_documents_storage()
    documents = await storage.list_documents(
        user_jwt=request.state.user_jwt, user_id=request.state.user["sub"]
    )
    return JSONResponse({"documents": documents}, status_code=200)


@router.post("/api/v1/documents/{document_id}/retry-ingest")
async def retry_ingest(request: Request, document_id: str, background_tasks: BackgroundTasks):
    """Retries a failed ingest job from wherever it's safe to resume —
    see check_retry_eligible's docstring for the embedding vs.
    normalizing/extracting split (Stage 7.5 closed the gap where only
    embed-stage failures were retryable)."""
    try:
        resume_stage = await check_retry_eligible(
            user_jwt=request.state.user_jwt, document_id=document_id
        )
    except RetryError as exc:
        status_code = 404 if exc.code == "not_found" else 409
        return _error(exc.code, exc.message, status_code)

    if resume_stage == "embedding":
        background_tasks.add_task(
            _embed_then_place,
            user_jwt=request.state.user_jwt,
            user_id=request.state.user["sub"],
            document_id=document_id,
        )
    elif resume_stage == "extracting":
        # Captured thought (Stage 5.5) — no normalize stage exists for it.
        background_tasks.add_task(
            _run_capture_pipeline,
            user_jwt=request.state.user_jwt,
            user_id=request.state.user["sub"],
            document_id=document_id,
        )
    else:  # "normalizing"
        background_tasks.add_task(
            _run_ingest_pipeline,
            user_jwt=request.state.user_jwt,
            user_id=request.state.user["sub"],
            document_id=document_id,
        )
    return JSONResponse({"id": document_id, "state": resume_stage}, status_code=202)


@router.get("/api/v1/documents/{document_id}")
async def get_document(request: Request, document_id: str):
    """Stage 3.6 — ingest_state/last_error are folded in directly rather
    than a separate GET /ingest-jobs/{id}: the frontend only ever has a
    document_id to poll with, never a raw ingest_jobs.id, so a second
    endpoint keyed by a different id space would add surface without
    adding capability."""
    storage = get_documents_storage()
    document = await storage.get_document(
        user_jwt=request.state.user_jwt, document_id=document_id
    )
    if document is None:
        return _error("not_found", "Document not found", 404)
    return JSONResponse(document, status_code=200)


async def _signed_url_response(request: Request, document_id: str, variant: str) -> JSONResponse:
    storage = get_documents_storage()
    try:
        url = await storage.get_signed_url(
            user_jwt=request.state.user_jwt, document_id=document_id, variant=variant
        )
    except DocumentsStorageError as exc:
        if exc.code == "not_found":
            return _error(exc.code, exc.message, 404)
        if exc.code == "document_sealed":
            return _error(exc.code, exc.message, 423)
        if exc.code == "not_available":
            return _error(exc.code, exc.message, 404)
        raise
    return JSONResponse({"url": url}, status_code=200)


@router.get("/api/v1/documents/{document_id}/download")
async def download_document(request: Request, document_id: str):
    """Signed URL to the normalized (indexed) file. A sealed document
    rejects this with 423 — sealing (Stage 3.3) only ever removed
    plaintext from `chunks`, never re-encrypted the Storage object
    itself, so a signed URL here would bypass the passphrase entirely
    if not blocked explicitly."""
    return await _signed_url_response(request, document_id, "indexed")


@router.get("/api/v1/documents/{document_id}/original")
async def download_original(request: Request, document_id: str):
    """Same sealed-document rejection as /download, same reasoning."""
    return await _signed_url_response(request, document_id, "original")


@router.post("/api/v1/documents/{document_id}/extract-action-items")
async def extract_action_items_route(request: Request, document_id: str):
    """Stage 4.6 — single-document action-item extraction. Returns
    candidates only; nothing is persisted here. Confirming a candidate
    is a normal POST /boards/{id}/cards with document_id set to this
    document (Stage 4.2's route already accepts it) — no separate
    confirm endpoint exists because none was needed."""
    candidates = await extract_action_items(
        user_jwt=request.state.user_jwt, document_id=document_id
    )
    if candidates is None:
        return _error("not_found", "Document not found", 404)
    return JSONResponse({"items": candidates}, status_code=200)


class RenameDocumentBody(BaseModel):
    title: str


@router.patch("/api/v1/documents/{document_id}")
async def rename_document(request: Request, document_id: str, body: RenameDocumentBody):
    title = body.title.strip()
    if not title:
        return _error("empty_title", "Title cannot be empty", 422)
    if len(title) > 500:
        return _error("title_too_long", "Title exceeds 500 characters", 413)

    storage = get_documents_storage()
    renamed = await storage.rename_document(
        user_jwt=request.state.user_jwt, document_id=document_id, title=title
    )
    if not renamed:
        return _error("not_found", "Document not found", 404)
    return JSONResponse({"id": document_id, "title": title}, status_code=200)


@router.delete("/api/v1/documents/{document_id}")
async def delete_document(request: Request, document_id: str):
    """Deletes both Storage objects (best-effort) then the documents
    row, which cascades chunks/sealed_chunks/ingest_jobs/
    document_clusters/document_edges/unlock_claims via each table's own
    FK — no new migration needed, every cascade was already declared.
    Works on sealed documents too; deleting only requires ownership
    (RLS), never the passphrase."""
    storage = get_documents_storage()
    deleted = await storage.delete_document(
        user_jwt=request.state.user_jwt, document_id=document_id
    )
    if not deleted:
        return _error("not_found", "Document not found", 404)
    return JSONResponse({"id": document_id, "deleted": True}, status_code=200)
