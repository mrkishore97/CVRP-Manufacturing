"""V1.1-M4 API: task import preview, import templates, and Review warnings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
V11_G = PROJECT_ROOT / "sample_data" / "v1_1" / "v11_g_vehicle_tags.json"
V11_F = PROJECT_ROOT / "sample_data" / "v1_1" / "v11_f_priority_shortage.json"
COMPAT_B = PROJECT_ROOT / "sample_data" / "v1_0_compat" / "scenario_b.json"


def _client(tmp_path: Path, **overrides: Any) -> TestClient:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "api.db",
        "google_maps_api_key": None,
        "_env_file": None,
        **overrides,
    }
    return TestClient(create_app(settings=Settings(**values)))


def _json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


TASK_ROWS = [
    {
        "PO": "PO-1",
        "Movement type": "PICKUP",
        "Pickup location": "Fixture Supplier A",
        "Qty": 4,
        "Ready": "2026-12-07 08:00",
        "Due": "2026-12-07 15:00",
        "Required tags": "refrigerated",
    },
    {
        "PO": "PO-2",
        "Movement type": "drop",
        "Drop location": "CUSTOMER_A",
        "Qty": 2.5,
        "Ready": "2026-12-07 08:00",
        "Due": "2026-12-07 15:00",
        "Priority": "High",
    },
]


def _task_request(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scenario = _json(V11_G)
    return {
        "rows": rows,
        "locations": [
            {"location_id": location["location_id"], "name": location["name"]}
            for location in scenario["locations"]
        ],
        "plant_location_id": "PLANT",
        "timezone": "America/Toronto",
        "default_pickup_service_minutes": 15,
        "default_delivery_service_minutes": 10,
    }


def test_task_import_preview_returns_canonical_rows(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/v1/imports/tasks/preview", json=_task_request(TASK_ROWS))

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    first, second = body["rows"]
    assert first["origin_location_id"] == "SUPPLIER_A"
    assert first["destination_location_id"] == "PLANT"
    assert first["required_vehicle_tags"] == ["REFRIGERATED"]
    assert first["pickup_service_minutes"] == 15
    assert first["delivery_service_minutes"] == 10
    assert first["quantity"] == 4
    assert second["origin_location_id"] == "PLANT"
    assert second["quantity"] == 2.5
    assert second["priority"] == 4


def test_imported_rows_validate_as_planning_tasks(tmp_path: Path) -> None:
    scenario = _json(V11_G)
    with _client(tmp_path) as client:
        preview = client.post("/api/v1/imports/tasks/preview", json=_task_request(TASK_ROWS))
        tasks = []
        for number, row in enumerate(preview.json()["rows"], start=1):
            task = {key: value for key, value in row.items() if key != "row_number"}
            task["task_id"] = f"TASK-IMP-{number}"
            tasks.append(task)
        scenario["tasks"] = tasks
        response = client.post("/api/v1/plans/validate", json=scenario)

    assert response.status_code == 200
    assert response.json()["validation"]["valid"] is True


def test_task_import_preview_reports_row_errors(tmp_path: Path) -> None:
    rows = [{**TASK_ROWS[0], "Pickup location": "Unknown supplier"}]
    with _client(tmp_path) as client:
        response = client.post("/api/v1/imports/tasks/preview", json=_task_request(rows))

    body = response.json()
    assert body["valid"] is False
    assert body["rows"] == []
    [issue] = body["issues"]
    assert issue["code"] == "UNKNOWN_LOCATION"
    assert issue["row_number"] == 2


def test_task_import_preview_respects_the_task_limit(tmp_path: Path) -> None:
    with _client(tmp_path, api_max_tasks=1) as client:
        response = client.post("/api/v1/imports/tasks/preview", json=_task_request(TASK_ROWS))

    assert response.status_code == 413
    assert response.json()["code"] == "TASK_LIMIT_EXCEEDED"


def test_import_templates_are_served_for_tasks_and_locations(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        tasks = client.get("/api/v1/imports/templates/tasks")
        locations = client.get("/api/v1/imports/templates/locations")
        unknown = client.get("/api/v1/imports/templates/trucks")

    assert tasks.status_code == 200
    columns = {column["name"]: column for column in tasks.json()["columns"]}
    assert columns["po_number"]["required"] is True
    assert columns["task_id"]["required"] is False
    assert "qty" in columns["quantity"]["aliases"]
    assert tasks.json()["example_rows"][0]["po_number"] == "PO-1001"
    assert [column["name"] for column in locations.json()["columns"]] == [
        "name",
        "address",
        "location_id",
    ]
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "UNKNOWN_IMPORT_KIND"


def test_validate_returns_review_warnings_with_sections(tmp_path: Path) -> None:
    scenario = _json(V11_G)
    scenario["vehicles"].append(
        {"vehicle_id": "SPARE-1", "name": "Spare", "capacity": 5, "enabled": True}
    )
    scenario["optimisation_options"] = {}
    with _client(tmp_path) as client:
        response = client.post("/api/v1/plans/validate", json=scenario)

    validation = response.json()["validation"]
    assert validation["valid"] is True
    by_code = {issue["code"]: issue for issue in validation["issues"]}
    assert by_code["VEHICLE_WITHOUT_SHIFT"]["section"] == "vehicles"
    assert by_code["VEHICLE_WITHOUT_SHIFT"]["item_id"] == "SPARE-1"
    assert by_code["UNKNOWN_FIELD"]["field"] == "optimisation_options"


def test_rejected_payload_details_say_which_entries_are_warnings(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/v1/plans/solve", json=_json(COMPAT_B))

    assert response.status_code == 422
    details = response.json()["details"]
    severities = {detail["code"]: detail["severity"] for detail in details}
    assert severities["CAPACITY_EXCEEDED"] == "ERROR"
    assert severities["UNUSED_LOCATION"] == "WARNING"
    capacity = next(detail for detail in details if detail["code"] == "CAPACITY_EXCEEDED")
    assert capacity["section"] == "tasks"
    assert capacity["item_id"] == "TASK-CAPACITY-001"


def test_solve_reports_priorities_on_a_partial_plan(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/v1/plans/solve", json=_json(V11_F))

    plan = response.json()["plan"]
    assert plan["status"] == "PARTIALLY_FEASIBLE"
    assert sorted(plan["scheduled_task_ids"]) == ["TASK-P4-4", "TASK-P5-5"]
    assert {diagnostic["priority"] for diagnostic in plan["diagnostics"]} == {1, 2, 3}
