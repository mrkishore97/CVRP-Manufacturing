"""A partial plan over sample A's IDs, shaped like the backend's plan JSON.

Two routes on 22 June 2026 (Toronto, UTC-4): Truck 1 does two pickups at Supplier A,
delivers to Hub A and back to the plant; Truck 2 takes a drop to Customer A and ends
past midnight. Three POs are not planned: one for lack of fleet time, one that cannot
meet its deadline (with an estimated finish), and one with no diagnostic at all.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from frontend.samples import load_sample_payload


def _stop(
    sequence: int,
    kind: str,
    location_id: str,
    at: str,
    *,
    task_id: str | None = None,
    depart: str | None = None,
    load: str = "0",
    meters: int = 0,
    seconds: int = 0,
    due_at: str | None = None,
    slack: int | None = None,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "node_id": f"N{sequence}-{kind}",
        "kind": kind,
        "location_id": location_id,
        "task_id": task_id,
        "arrival_at": at,
        "service_start_at": at,
        "departure_at": depart or at,
        "load_after": load,
        "distance_from_previous_meters": meters,
        "duration_from_previous_seconds": seconds,
        "due_at": due_at,
        "slack_seconds": slack,
    }


ROUTE_1: dict[str, Any] = {
    "vehicle_id": "TRUCK-1",
    "shift_id": "TRUCK-1-20260622",
    "total_distance_meters": 64_500,
    "driving_seconds": 5_400,
    "service_seconds": 3_600,
    "waiting_seconds": 600,
    "peak_load": "7",
    "total_duration_seconds": 9_600,
    "stops": [
        _stop(0, "DEPOT_START", "PLANT", "2026-06-22T11:00:00Z"),
        _stop(
            1,
            "PICKUP",
            "SUPPLIER_A",
            "2026-06-22T11:30:00Z",
            task_id="TASK-PICK-001",
            depart="2026-06-22T11:45:00Z",
            load="4",
            meters=20_000,
            seconds=1_800,
        ),
        _stop(
            2,
            "PICKUP",
            "SUPPLIER_A",
            "2026-06-22T11:45:00Z",
            task_id="TASK-PAIR-001",
            depart="2026-06-22T12:00:00Z",
            load="7",
        ),
        _stop(
            3,
            "DELIVERY",
            "HUB_A",
            "2026-06-22T12:30:00Z",
            task_id="TASK-PAIR-001",
            depart="2026-06-22T12:45:00Z",
            load="4",
            meters=22_000,
            seconds=1_800,
            due_at="2026-06-22T19:00:00Z",
            slack=23_400,
        ),
        _stop(
            4,
            "DELIVERY",
            "PLANT",
            "2026-06-22T13:30:00Z",
            task_id="TASK-PICK-001",
            depart="2026-06-22T13:40:00Z",
            meters=22_500,
            seconds=1_800,
            due_at="2026-06-22T16:30:00Z",
            slack=9_600,
        ),
        _stop(5, "DEPOT_END", "PLANT", "2026-06-22T13:40:00Z"),
    ],
}
ROUTE_2: dict[str, Any] = {
    "vehicle_id": "TRUCK-2",
    "shift_id": "TRUCK-2-20260622",
    "total_distance_meters": 30_000,
    "driving_seconds": 3_000,
    "service_seconds": 1_800,
    "waiting_seconds": 0,
    "peak_load": "5",
    "stops": [
        _stop(0, "DEPOT_START", "PLANT", "2026-06-23T02:00:00Z"),
        _stop(
            1,
            "PICKUP",
            "PLANT",
            "2026-06-23T02:00:00Z",
            task_id="TASK-DROP-001",
            depart="2026-06-23T02:15:00Z",
            load="5",
        ),
        _stop(
            2,
            "DELIVERY",
            "CUSTOMER_A",
            "2026-06-23T03:00:00Z",
            task_id="TASK-DROP-001",
            depart="2026-06-23T03:15:00Z",
            meters=15_000,
            seconds=1_500,
            due_at="2026-06-23T04:00:00Z",
            slack=2_700,
        ),
        _stop(
            3,
            "DEPOT_END",
            "PLANT",
            "2026-06-23T04:05:00Z",
            meters=15_000,
            seconds=1_500,
        ),
    ],
}


def sample_scenario() -> dict[str, Any]:
    return load_sample_payload("A", include_matrix=False)


def partial_plan(**overrides: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "plan_id": "PLAN-20260622T100000Z-abcdef12",
        "status": "PARTIALLY_FEASIBLE",
        "created_at": "2026-06-22T10:00:00Z",
        "routes": [deepcopy(ROUTE_1), deepcopy(ROUTE_2)],
        "scheduled_task_ids": ["TASK-PICK-001", "TASK-PAIR-001", "TASK-DROP-001"],
        "unscheduled_task_ids": ["TASK-DROP-002", "TASK-PAIR-002", "TASK-PICK-002"],
        "diagnostics": [
            {
                "task_id": "TASK-DROP-002",
                "po_number": "PO-DROP-002",
                "code": "INSUFFICIENT_COMBINED_FLEET_TIME",
                "message": "Backend wording.",
                "due_at": "2026-06-22T18:00:00Z",
                "priority": 2,
            },
            {
                "task_id": "TASK-PAIR-002",
                "po_number": "PO-PAIR-002",
                "code": "DEADLINE_IMPOSSIBLE_INDIVIDUALLY",
                "message": "Backend wording.",
                "due_at": "2026-06-22T20:30:00Z",
                "estimated_completion_at": "2026-06-22T21:15:00Z",
                "late_by_seconds": 2_700,
                "priority": 3,
            },
        ],
        "total_distance_meters": 94_500,
        "total_driving_seconds": 8_400,
        "total_service_seconds": 5_400,
        "total_waiting_seconds": 600,
        "solver_elapsed_seconds": 0.4,
        "optimization_options": {
            "objective_mode": "BALANCE_WORKLOAD",
            "search_effort": "THOROUGH",
            "time_limit_seconds": 20,
            "travel_time_factor": 1.2,
            "extra_truck_cost_km": 1_000,
            "balance_strength": "LIGHT",
        },
        "matrix": {
            "source": "google_routes",
            "routing_preference": "TRAFFIC_UNAWARE",
            "created_at": "2026-06-21T14:00:00Z",
            "location_count": 7,
            "travel_time_factor": 1.2,
        },
        "metrics": {
            "truck_shifts_used": 2,
            "truck_shifts_available": 6,
            "longest_route_seconds": 9_600,
            "shortest_route_seconds": 7_500,
            "longest_working_seconds": 9_000,
            "load_utilisation": 0.6,
            "time_utilisation": 0.3,
        },
        "input_fingerprint": "v1:" + "a" * 64,
    }
    plan.update(overrides)
    return plan
