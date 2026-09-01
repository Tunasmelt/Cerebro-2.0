import os

from fastapi import FastAPI, Request

from app.core.middleware import AuthMiddleware
from app.core.rate_limit_middleware import RateLimitMiddleware
from app.routes.chat import router as chat_router
from app.routes.documents import router as documents_router
from app.routes.graph import router as graph_router

app = FastAPI()
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(graph_router)
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
