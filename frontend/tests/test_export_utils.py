"""Plan export utility tests."""

from io import BytesIO

from openpyxl import load_workbook

from frontend.export_utils import (
    build_export_tables,
    diagnostics_csv_bytes,
    route_stops_csv_bytes,
    workbook_bytes,
)


def _plan() -> dict[str, object]:
    return {
        "plan_id": "PLAN-1",
        "status": "PARTIAL",
        "scheduled_task_ids": ["TASK-1", "TASK-2"],
        "unscheduled_task_ids": ["=TASK-UNSCHEDULED"],
        "total_distance_meters": 300,
        "routes": [
            {
                "vehicle_id": "TRUCK-1",
                "shift_id": "SHIFT-1",
                "total_distance_meters": 100,
                "driving_seconds": 60,
                "service_seconds": 30,
                "waiting_seconds": 0,
                "peak_load": "4",
                "stops": [
                    {
                        "sequence": 0,
                        "node_id": "START",
                        "kind": "DEPOT_START",
                        "location_id": "PLANT",
                        "task_id": None,
                        "arrival_at": "2026-06-22T07:00:00-04:00",
                        "service_start_at": "2026-06-22T07:00:00-04:00",
                        "departure_at": "2026-06-22T07:00:00-04:00",
                        "load_after": "0",
                        "distance_from_previous_meters": 0,
                        "duration_from_previous_seconds": 0,
                        "due_at": None,
                        "slack_seconds": None,
                    },
                    {
                        "sequence": 1,
                        "node_id": "TASK-1-PICKUP",
                        "kind": "PICKUP",
                        "location_id": "SUPPLIER",
                        "task_id": "TASK-1",
                        "arrival_at": "2026-06-22T08:00:00-04:00",
                        "service_start_at": "2026-06-22T08:00:00-04:00",
                        "departure_at": "2026-06-22T08:15:00-04:00",
                        "load_after": "4",
                        "distance_from_previous_meters": 100,
                        "duration_from_previous_seconds": 60,
                        "due_at": "2026-06-22T12:00:00-04:00",
                        "slack_seconds": 3600,
                    },
                ],
            },
            {
                "vehicle_id": "TRUCK-2",
                "shift_id": "SHIFT-2",
                "total_distance_meters": 200,
                "driving_seconds": 120,
                "service_seconds": 30,
                "waiting_seconds": 0,
                "peak_load": "5",
                "stops": [
                    {
                        "sequence": 0,
                        "node_id": "START-2",
                        "kind": "DEPOT_START",
                        "location_id": "PLANT",
                        "task_id": None,
                        "arrival_at": "2026-06-22T07:00:00-04:00",
                        "service_start_at": "2026-06-22T07:00:00-04:00",
                        "departure_at": "2026-06-22T07:00:00-04:00",
                        "load_after": "0",
                        "distance_from_previous_meters": 0,
                        "duration_from_previous_seconds": 0,
                        "due_at": None,
                        "slack_seconds": None,
                    }
                ],
            },
        ],
        "diagnostics": [
            {
                "task_id": "+TASK-LATE",
                "po_number": "@PO-LATE",
                "code": "LATE",
                "message": "=Potential spreadsheet formula",
                "due_at": "2026-06-22T12:00:00-04:00",
                "estimated_completion_at": "2026-06-22T13:00:00-04:00",
                "late_by_seconds": 3600,
            }
        ],
    }


def test_export_tables_include_all_routes_and_unscheduled_tasks() -> None:
    tables = build_export_tables(_plan())

    assert len(tables.route_summary_rows) == 2
    assert len(tables.route_stop_rows) == 3
    diagnostic_task_ids = {row["task_id"] for row in tables.diagnostic_rows}
    assert diagnostic_task_ids == {"+TASK-LATE", "=TASK-UNSCHEDULED"}


def test_csv_exports_escape_formula_like_cells_and_preserve_timezone_labels() -> None:
    diagnostics_csv = diagnostics_csv_bytes(_plan()).decode("utf-8-sig")
    stops_csv = route_stops_csv_bytes(_plan()).decode("utf-8-sig")

    assert "'=Potential spreadsheet formula" in diagnostics_csv
    assert "'+TASK-LATE" in diagnostics_csv
    assert "'@PO-LATE" in diagnostics_csv
    assert "'=TASK-UNSCHEDULED" in diagnostics_csv
    assert "2026-06-22T08:00:00-04:00" in stops_csv


def test_workbook_contains_summary_diagnostics_and_detailed_stop_sheets() -> None:
    workbook = load_workbook(BytesIO(workbook_bytes(_plan())))

    assert set(workbook.sheetnames) >= {
        "Plan Summary",
        "Route Summary",
        "Route Stops",
        "Diagnostics",
        "TRUCK-1-SHIFT-1",
        "TRUCK-2-SHIFT-2",
    }
    diagnostics = workbook["Diagnostics"]
    assert diagnostics["D2"].value == "LATE"
    assert diagnostics["E2"].value == "'=Potential spreadsheet formula"
    route_stops = workbook["Route Stops"]
    assert route_stops["I3"].value == "2026-06-22T08:00:00-04:00"


def test_export_generation_handles_empty_partial_plan() -> None:
    plan = {
        "plan_id": "EMPTY-PARTIAL",
        "status": "PARTIAL",
        "scheduled_task_ids": [],
        "unscheduled_task_ids": ["TASK-NOT-SCHEDULED"],
        "routes": [],
        "diagnostics": [],
    }

    tables = build_export_tables(plan)

    assert tables.route_stop_rows == ()
    assert tables.diagnostic_rows[0]["task_id"] == "TASK-NOT-SCHEDULED"
    assert route_stops_csv_bytes(plan)
    assert diagnostics_csv_bytes(plan)
    assert workbook_bytes(plan)
