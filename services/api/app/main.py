import os

from fastapi import FastAPI, Request

from app.core.middleware import AuthMiddleware

app = FastAPI()
app.add_middleware(AuthMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "build_sha": os.environ.get("BUILD_SHA", "dev"), "stage_0_4_probe": "render-deploy-check"}


@app.get("/api/v1/_probe")
def probe(request: Request) -> dict:
    """Stage 0.5 probe route — proves AuthMiddleware actually reaches a
    handler on a valid token, not a real product endpoint."""
    return {"ok": True, "user_id": request.state.user["sub"]}
