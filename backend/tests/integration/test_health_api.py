"""FastAPI health-contract integration tests.

Every app here uses a temporary database: the backend's start-up prepares the schema
and runs the retention sweeps, which must never touch the planner's real database.
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _settings(tmp_path: Path, **values: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        database_path=tmp_path / "health.db",
        _env_file=None,
        **values,
    )


def test_health_endpoint_has_stable_contract_without_google_key(tmp_path: Path) -> None:
    settings = _settings(tmp_path, app_environment="test", google_maps_api_key=None)

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "manufacturing-po-route-optimizer-backend",
        "version": (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "environment": "test",
    }


def test_openapi_reports_release_version(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/openapi.json")

    expected = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert response.json()["info"]["version"] == expected


def test_openapi_exposes_versioned_health_route(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
