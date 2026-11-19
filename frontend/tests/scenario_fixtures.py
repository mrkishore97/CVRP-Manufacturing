"""Small scenarios shared by the frontend state tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from frontend.state.readiness import geocode_fingerprint
from frontend.state.workspace import (
    Workspace,
    load_document,
    record_matrix,
    record_plan,
    record_validation,
    validation_payload_fingerprint,
)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
SUPPLIER_ADDRESS = "200 Supplier Avenue, Vaughan, ON"


def small_scenario() -> dict[str, Any]:
    """Plant (supplied coordinates), a Google-resolved supplier, and an unused spare."""
    return {
        "scenario_id": "M2-FRESHNESS",
        "name": "Freshness fixture",
        "timezone": "America/Toronto",
        "planning_horizon": {"start": "2026-06-22T07:00:00", "end": "2026-06-22T17:00:00"},
        "plant_location_id": "PLANT",
        "locations": [
            {
                "location_id": "PLANT",
                "name": "Plant",
                "address": "100 Plant Road, Toronto, ON",
                "latitude": 43.7,
                "longitude": -79.4,
            },
            {
                "location_id": "SUPPLIER_A",
                "name": "Supplier A",
                "address": SUPPLIER_ADDRESS,
                "formatted_address": "200 Supplier Ave, Vaughan, ON, Canada",
                "place_id": "supplier-place",
                "latitude": 43.82,
                "longitude": -79.5,
                "geocode_status": "RESOLVED",
                "geocode_source_fingerprint": geocode_fingerprint(SUPPLIER_ADDRESS, "ca"),
                "geocoded_at": (NOW - timedelta(days=2)).isoformat(),
                "geocode_location_type": "ROOFTOP",
                "geocode_partial_match": False,
                "geocode_confirmed": False,
            },
            {
                "location_id": "SPARE",
                "name": "Spare dock",
                "address": "300 Spare Street, Toronto, ON",
                "latitude": 43.65,
                "longitude": -79.38,
            },
        ],
        "vehicles": [{"vehicle_id": "TRUCK-1", "name": "Truck 1", "capacity": 10, "enabled": True}],
        "vehicle_shifts": [
            {
                "shift_id": "TRUCK-1-20260622",
                "vehicle_id": "TRUCK-1",
                "start": "2026-06-22T07:00:00",
                "end": "2026-06-22T17:00:00",
            }
        ],
        "tasks": [
            {
                "task_id": "TASK-0001",
                "po_number": "PO-1",
                "task_type": "PICKUP",
                "origin_location_id": "SUPPLIER_A",
                "destination_location_id": "PLANT",
                "quantity": 4,
                "ready_at": "2026-06-22T07:00:00",
                "due_at": "2026-06-22T12:00:00",
                "due_event": "DELIVERY_COMPLETE",
                "notes": "Dock 4",
            }
        ],
        "routing_options": {"routing_preference": "TRAFFIC_UNAWARE"},
        "optimization_options": {"objective": "MINIMIZE_TRUCKS"},
        "planner_defaults": {"capacity_unit_label": "units"},
    }


def small_matrix() -> dict[str, Any]:
    return {
        "location_ids": ["PLANT", "SUPPLIER_A", "SPARE"],
        "distance_meters": [[0, 28_000, 6_000], [27_000, 0, 30_000], [6_500, 31_000, 0]],
        "duration_seconds": [[0, 1_800, 600], [1_700, 0, 2_000], [650, 2_100, 0]],
        "source": "test",
    }


def current_workspace() -> Workspace:
    """Validated, with current travel times and a current plan."""
    workspace = load_document(small_scenario(), source="test")
    workspace = record_matrix(workspace, small_matrix(), origin="calculated")
    workspace = record_validation(
        workspace,
        payload_fingerprint=validation_payload_fingerprint(workspace),
        validation={"valid": True, "issues": []},
        request_id="req-validate",
    )
    return record_plan(
        workspace,
        plan={"plan_id": "PLAN-1", "status": "FEASIBLE"},
        validation=None,
        request_id="req-solve",
    )
