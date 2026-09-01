from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.graph.cluster import run_clustering_job

router = APIRouter()


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
