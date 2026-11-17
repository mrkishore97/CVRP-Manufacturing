"""FastAPI health-contract integration tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
        "version": (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "environment": "test",
    }


def test_openapi_reports_release_version() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as client:
        response = client.get("/openapi.json")

    expected = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert response.json()["info"]["version"] == expected


def test_openapi_exposes_versioned_health_route() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
