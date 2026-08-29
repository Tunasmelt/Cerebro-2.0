from fastapi.testclient import TestClient

from app.main import app
from app.types_stub import SCHEMA_VERSION


def test_health_returns_200():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["stage_0_4_probe"] == "render-deploy-check"


def test_types_package_imports_cleanly():
    assert SCHEMA_VERSION == "0.0.1"
