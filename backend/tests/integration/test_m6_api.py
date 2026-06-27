"""M6 FastAPI workflow, error, and persistence contract tests."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.domain.enums import PlanStatus
from backend.app.domain.models import RoutingMatrix
from backend.app.persistence import SQLiteDatabase, SQLiteScenarioRepository
from backend.app.routing import FakeRoutingProvider, RoutingLocation
from backend.tests.fixtures.canonical import planning_payload


def _settings(tmp_path: Path, **updates: Any) -> Settings:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "api.db",
        "google_maps_api_key": None,
        "_env_file": None,
    }
    values.update(updates)
    return Settings(**values)


def _simple_locations() -> tuple[RoutingLocation, RoutingLocation]:
    return (
        RoutingLocation("PLANT", "100 Plant Road, Toronto, ON", 43.7, -79.4, "plant-place"),
        RoutingLocation(
            "SUPPLIER_A",
            "200 Supplier Avenue, Vaughan, ON",
            43.82,
            -79.5,
            "supplier-place",
        ),
    )


def _simple_matrix() -> RoutingMatrix:
    return RoutingMatrix(
        location_ids=("PLANT", "SUPPLIER_A"),
        distance_meters=((0, 28_000), (27_000, 0)),
        duration_seconds=((0, 1_800), (1_700, 0)),
        source="fake",
    )


def _app_with_fake_provider(tmp_path: Path) -> tuple[FastAPI, FakeRoutingProvider]:
    plant, supplier = _simple_locations()
    provider = FakeRoutingProvider(
        geocodes={
            "100 Plant Road": plant,
            "200 Supplier Avenue": supplier,
        },
        matrix=_simple_matrix(),
    )
    app = create_app(_settings(tmp_path))
    app.state.routing_provider = provider
    return app, provider


def _planning_payload_from_workflow(
    *,
    locations_payload: list[dict[str, Any]],
    matrix_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "scenario_id": "API-SIMPLE",
        "timezone": "America/Toronto",
        "planning_horizon": {
            "start": "2026-06-22T07:00:00-04:00",
            "end": "2026-06-22T17:00:00-04:00",
        },
        "plant_location_id": "PLANT",
        "locations": [
            {
                "location_id": location["location_id"],
                "name": location["location_id"].replace("_", " ").title(),
                "address": location["formatted_address"],
                "formatted_address": location["formatted_address"],
                "place_id": location["place_id"],
                "latitude": location["latitude"],
                "longitude": location["longitude"],
            }
            for location in locations_payload
        ],
        "vehicles": [
            {
                "vehicle_id": "TRUCK-1",
                "name": "Truck 1",
                "capacity": 12,
                "enabled": True,
            }
        ],
        "vehicle_shifts": [
            {
                "shift_id": "TRUCK-1-20260622",
                "vehicle_id": "TRUCK-1",
                "start": "2026-06-22T07:00:00-04:00",
                "end": "2026-06-22T17:00:00-04:00",
            }
        ],
        "tasks": [
            {
                "task_id": "TASK-API-001",
                "po_number": "PO-API-001",
                "task_type": "PICKUP",
                "origin_location_id": "SUPPLIER_A",
                "destination_location_id": "PLANT",
                "quantity": 4,
                "ready_at": "2026-06-22T07:00:00-04:00",
                "due_at": "2026-06-22T12:30:00-04:00",
                "due_event": "DELIVERY_COMPLETE",
                "pickup_service_minutes": 15,
                "delivery_service_minutes": 15,
            }
        ],
        "routing_matrix": matrix_payload,
    }


def test_geocode_matrix_validate_solve_and_retrieve_plan_workflow(tmp_path: Path) -> None:
    app, provider = _app_with_fake_provider(tmp_path)
    with TestClient(app) as client:
        geocode_response = client.post(
            "/api/v1/locations/geocode",
            json={"addresses": ["100 Plant Road", "200 Supplier Avenue"]},
            headers={"X-Request-ID": "api-workflow"},
        )
        assert geocode_response.status_code == 200
        assert geocode_response.headers["X-Request-ID"] == "api-workflow"
        locations = geocode_response.json()["locations"]

        matrix_response = client.post(
            "/api/v1/matrices/compute",
            json={"locations": locations},
        )
        assert matrix_response.status_code == 200
        matrix_body = matrix_response.json()
        assert not matrix_body["cache_hit"]
        assert provider.matrix_call_count == 1

        second_matrix_response = client.post(
            "/api/v1/matrices/compute",
            json={"locations": locations},
        )
        assert second_matrix_response.status_code == 200
        assert second_matrix_response.json()["cache_hit"]
        assert provider.matrix_call_count == 1

        payload = _planning_payload_from_workflow(
            locations_payload=locations,
            matrix_payload=matrix_body["matrix"],
        )
        validation_response = client.post("/api/v1/plans/validate", json=payload)
        assert validation_response.status_code == 200
        assert validation_response.json()["validation"]["valid"]

        solve_response = client.post("/api/v1/plans/solve", json=payload)
        assert solve_response.status_code == 200
        solve_body = solve_response.json()
        assert solve_body["plan"]["status"] == PlanStatus.FEASIBLE
        assert solve_body["plan"]["scheduled_task_ids"] == ["TASK-API-001"]

        plan_id = solve_body["plan"]["plan_id"]
        get_response = client.get(f"/api/v1/plans/{plan_id}")
        assert get_response.status_code == 200
        assert get_response.json()["plan"]["plan_id"] == plan_id

        export_response = client.get(f"/api/v1/plans/{plan_id}/export")
        assert export_response.status_code == 200
        assert export_response.json()["route_rows"]


def test_solve_returns_structured_validation_error_for_invalid_payload(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/plans/solve",
            json=planning_payload("B"),
            headers={"X-Request-ID": "validation-error"},
        )

    assert response.status_code == 422
    assert response.headers["X-Request-ID"] == "validation-error"
    body = response.json()
    assert body["request_id"] == "validation-error"
    assert body["code"] == "PLANNING_VALIDATION_FAILED"
    assert any(detail["code"] == "CAPACITY_EXCEEDED" for detail in body["details"])


def test_request_validation_error_uses_request_id_envelope(tmp_path: Path) -> None:
    app, _provider = _app_with_fake_provider(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/locations/geocode",
            json={"addresses": [""]},
            headers={"X-Request-ID": "bad-geocode"},
        )

    assert response.status_code == 422
    assert response.json()["request_id"] == "bad-geocode"
    assert response.json()["code"] == "REQUEST_VALIDATION_ERROR"


def test_unexpected_backend_error_does_not_leak_traceback_or_secret(tmp_path: Path) -> None:
    class ExplodingPlanningService:
        def optimize(self, request: object) -> object:
            del request
            raise RuntimeError("secret implementation detail")

    app, _provider = _app_with_fake_provider(tmp_path)
    app.state.planning_service = ExplodingPlanningService()
    plant, supplier = _simple_locations()
    payload = _planning_payload_from_workflow(
        locations_payload=[
            {
                "location_id": plant.location_id,
                "formatted_address": plant.formatted_address,
                "latitude": plant.latitude,
                "longitude": plant.longitude,
                "place_id": plant.place_id,
            },
            {
                "location_id": supplier.location_id,
                "formatted_address": supplier.formatted_address,
                "latitude": supplier.latitude,
                "longitude": supplier.longitude,
                "place_id": supplier.place_id,
            },
        ],
        matrix_payload=json.loads(_simple_matrix().model_dump_json()),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/plans/solve",
            json=payload,
            headers={"X-Request-ID": "boom"},
        )

    assert response.status_code == 500
    body_text = response.text
    assert "secret implementation detail" not in body_text
    assert "Traceback" not in body_text
    assert response.json()["request_id"] == "boom"
    assert response.json()["code"] == "INTERNAL_SERVER_ERROR"


def test_scenario_create_update_and_retrieve(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    payload = planning_payload("A")
    with TestClient(app) as client:
        create_response = client.post("/api/v1/scenarios", json=payload)
        assert create_response.status_code == 201
        assert create_response.json()["scenario_id"] == "A"

        get_response = client.get("/api/v1/scenarios/A")
        assert get_response.status_code == 200
        assert get_response.json()["payload"]["scenario_id"] == "A"

        updated = {**payload, "name": "Updated scenario"}
        update_response = client.put("/api/v1/scenarios/A", json=updated)
        assert update_response.status_code == 200
        assert update_response.json()["payload"]["name"] == "Updated scenario"


def test_request_size_limit_is_enforced_before_route_logic(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, api_max_request_bytes=1024))
    oversized = json.dumps({"scenario_id": "BIG", "notes": "x" * 2_000})
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/plans/validate",
            content=oversized,
            headers={"Content-Type": "application/json", "X-Request-ID": "too-big"},
        )

    assert response.status_code == 413
    assert response.json()["request_id"] == "too-big"
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_openapi_schema_contains_m6_routes(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in (
        "/api/v1/health",
        "/api/v1/locations/geocode",
        "/api/v1/matrices/compute",
        "/api/v1/plans/validate",
        "/api/v1/plans/solve",
        "/api/v1/scenarios",
        "/api/v1/scenarios/{scenario_id}",
        "/api/v1/plans/{plan_id}",
        "/api/v1/plans/{plan_id}/export",
    ):
        assert path in paths


def test_database_transaction_rolls_back_on_failed_write(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "rollback.db")
    try:
        with database.connect() as connection:
            connection.execute("CREATE TABLE example (id TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO example (id) VALUES ('rolled-back')")
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass

    with database.connect() as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS example (id TEXT PRIMARY KEY)")
        count = connection.execute("SELECT COUNT(*) FROM example").fetchone()[0]

    assert count == 0


def test_concurrent_scenario_reads_are_safe(tmp_path: Path) -> None:
    repository = SQLiteScenarioRepository(SQLiteDatabase(tmp_path / "concurrent.db"))
    repository.save("A", planning_payload("A"))

    def read_scenario() -> str:
        scenario = repository.get("A")
        assert scenario is not None
        return str(scenario.payload["scenario_id"])

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(lambda _: read_scenario(), range(16)))

    assert results == ("A",) * 16
