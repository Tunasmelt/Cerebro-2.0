import os

from dotenv import load_dotenv

# Must run before any app.* import below — several modules construct a
# storage singleton at import time (e.g. documents_storage.py's
# `_storage = SupabaseDocumentsStorage()`) whose __init__ reads
# SUPABASE_URL/SUPABASE_ANON_KEY from os.environ immediately. Render sets
# real env vars directly so this is a no-op there; locally it loads
# services/api/.env for `uvicorn app.main:app` to work without exporting
# vars by hand.
load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402

from app.core.middleware import AuthMiddleware  # noqa: E402
from app.core.rate_limit_middleware import RateLimitMiddleware  # noqa: E402
from app.routes.chat import router as chat_router  # noqa: E402
from app.routes.documents import router as documents_router  # noqa: E402
from app.routes.graph import router as graph_router  # noqa: E402
from app.routes.account import router as account_router  # noqa: E402
from app.routes.kanban import router as kanban_router  # noqa: E402
from app.routes.sealed import router as sealed_router  # noqa: E402
from app.routes.todos import router as todos_router  # noqa: E402

app = FastAPI()
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(graph_router)
app.include_router(sealed_router)
app.include_router(kanban_router)
app.include_router(todos_router)
app.include_router(account_router)
# Starlette runs middleware in reverse add-order on the way in, so the
# middleware added last runs first. AuthMiddleware must run before
# RateLimitMiddleware (it needs request.state.user), hence this order.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "build_sha": os.environ.get("BUILD_SHA", "dev"), "stage_0_4_probe": "render-deploy-check"}


@app.get("/api/v1/_probe")
def probe(request: Request) -> dict:
    """Stage 0.5 probe route — proves AuthMiddleware actually reaches a
    handler on a valid token, not a real product endpoint."""
    return {"ok": True, "user_id": request.state.user["sub"]}
