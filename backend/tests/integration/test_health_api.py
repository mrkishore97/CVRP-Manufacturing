"""FastAPI health-contract integration tests."""

from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.config import Settings


def test_health_endpoint_has_stable_contract_without_google_key() -> None:
    settings = Settings(  # type: ignore[call-arg]
        app_environment="test",
        google_maps_api_key=None,
        _env_file=None,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "manufacturing-po-route-optimizer-backend",
        "version": "0.1.0",
        "environment": "test",
    }


def test_openapi_exposes_versioned_health_route() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
