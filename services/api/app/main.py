import os

from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "build_sha": os.environ.get("BUILD_SHA", "dev"), "stage_0_4_probe": "render-deploy-check"}
