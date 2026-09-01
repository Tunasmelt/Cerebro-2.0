from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.graph.api import get_edges, get_node_chunks, get_nodes
from app.graph.cluster import run_clustering_job

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
async def edges(request: Request):
    """kNN edges as of the last recluster run — these DO go stale
    relative to new uploads until the next recluster, unlike nodes; see
    architecture-and-security.md's Clustering pipeline section."""
    result = await get_edges(user_jwt=request.state.user_jwt)
    return JSONResponse({"edges": result})


@router.get("/api/v1/graph/nodes/{document_id}/chunks")
async def node_chunks(request: Request, document_id: str):
    result = await get_node_chunks(
        user_jwt=request.state.user_jwt, document_id=document_id
    )
    if result is None:
        return _error("not_found", "Document not found", 404)
    return JSONResponse({"chunks": result})
