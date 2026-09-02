from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.graph.api import get_edges, get_node_chunks, get_nodes
from app.graph.cluster import run_clustering_job
from app.graph.edges import get_associative_document_edges, get_chunk_edges_storage

router = APIRouter()


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


@router.post("/api/v1/graph/recluster")
async def recluster(request: Request, background_tasks: BackgroundTasks):
    """Triggers a full re-cluster (Stage 2.1 — this stage always
    recomputes everything; Stage 2.5 adds incremental placement for new
    uploads instead of a full recompute every time). Runs as a
    BackgroundTask, same in-process pattern as the ingest pipeline —
    no separate worker, per CLAUDE.md's Render free-tier constraint."""
    background_tasks.add_task(
        run_clustering_job,
        user_jwt=request.state.user_jwt,
        user_id=request.state.user["sub"],
    )
    return JSONResponse({"status": "recluster_started"}, status_code=202)


@router.get("/api/v1/graph/nodes")
async def nodes(request: Request):
    """Every ready document, current as of this call — a document
    uploaded since the last recluster still appears (with cluster_id/x/y
    null) rather than being missing, per the exit criteria's "no
    stale/missing nodes after an upload or delete"."""
    result = await get_nodes(user_jwt=request.state.user_jwt)
    return JSONResponse({"nodes": result})


@router.get("/api/v1/graph/edges")
async def edges(request: Request, include: str | None = None):
    """kNN edges as of the last recluster run — these DO go stale
    relative to new uploads until the next recluster, unlike nodes; see
    architecture-and-security.md's Clustering pipeline section.

    Stage 5.4 — ?include=associative additionally returns
    associative_edges: Stage 5.3's chunk_edges aggregated up to
    document pairs (a chunk-level table; the graph only shows document
    nodes). Additive, not a breaking response shape change — the
    `edges` key and its shape are exactly what they were before this
    param existed, so every pre-5.4 caller keeps working unmodified."""
    result = await get_edges(user_jwt=request.state.user_jwt)
    body: dict = {"edges": result}
    if include and "associative" in include.split(","):
        body["associative_edges"] = await get_associative_document_edges(
            user_jwt=request.state.user_jwt
        )
    return JSONResponse(body)


@router.get("/api/v1/graph/nodes/{document_id}/chunks")
async def node_chunks(request: Request, document_id: str):
    result = await get_node_chunks(
        user_jwt=request.state.user_jwt, document_id=document_id
    )
    if result is None:
        return _error("not_found", "Document not found", 404)
    return JSONResponse({"chunks": result})


class LinkChunkBody(BaseModel):
    target_chunk_id: str


@router.post("/api/v1/chunks/{chunk_id}/link")
async def link_chunk(request: Request, chunk_id: str, body: LinkChunkBody):
    """Stage 5.3 — an explicit, user-drawn associative edge. Both chunks
    must be the caller's own (RLS-scoped lookup inside
    create_explicit_link, same pattern kanban_storage.create_card already
    uses for board_id) — a chunk_id belonging to another user, or one
    that no longer exists (e.g. a sealed document's, already deleted),
    is indistinguishable from "not found" here, never a 403."""
    storage = get_chunk_edges_storage()
    edge = await storage.create_explicit_link(
        user_jwt=request.state.user_jwt,
        user_id=request.state.user["sub"],
        chunk_id_a=chunk_id,
        chunk_id_b=body.target_chunk_id,
    )
    if edge is None:
        return _error("not_found", "One or both chunks were not found", 404)
    return JSONResponse(
        {
            "id": edge.id,
            "source_chunk_id": edge.source_chunk_id,
            "target_chunk_id": edge.target_chunk_id,
            "weight": edge.weight,
            "is_explicit": edge.is_explicit,
        },
        status_code=201,
    )
