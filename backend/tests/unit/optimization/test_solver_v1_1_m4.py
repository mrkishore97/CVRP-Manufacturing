"""V1.1-M4 solver and validator completion (plan §10.4, §10.5, §10.7).

- Priority: all tasks are scheduled when they fit, whatever their priority; when they
  do not, higher priorities are kept (fixture V11-F); weights are monotonic; a task's
  pickup and delivery are kept or dropped together.
- Route distance: enforced by the solver, rejected by the validator when violated, and
  reported per task when no truck can reach a task within its limit (V11-H).
- The validator rejects plans that break tag, duration, or distance rules (V11-G, H).
- Shifts may end away from the plant (V11-I).
"""

from __future__ import annotations

import json
from datetime import timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from backend.app.config import Settings
from backend.app.domain import PlanStatus, validate_planning_payload
from backend.app.domain.models import PlanningRequest
from backend.app.domain.options import PRIORITY_LABELS, PRIORITY_WEIGHTS, priority_weight
from backend.app.domain.results import PlanResult
from backend.app.optimization import validate_plan_result
from backend.app.optimization.solver import OrToolsCapacitySolver, SolverConfig
from backend.tests.fixtures.canonical import planning_payload

V1_1_DIR = Path(__file__).resolve().parents[4] / "sample_data" / "v1_1"
FIXTURES = {
    "F": "v11_f_priority_shortage.json",
    "G": "v11_g_vehicle_tags.json",
    "H": "v11_h_route_limits.json",
    "I": "v11_i_multiday_shift_depots.json",
}


def _payload(letter: str) -> dict[str, Any]:
    with (V1_1_DIR / FIXTURES[letter]).open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def _request(payload: dict[str, Any]) -> PlanningRequest:
    result = validate_planning_payload(payload)
    assert result.valid, result.issues
    assert result.normalized_request is not None
    return result.normalized_request


def _solve(request: PlanningRequest) -> PlanResult:
    return OrToolsCapacitySolver(SolverConfig(time_limit_seconds=5)).solve(request)


def _route_of(plan: PlanResult, task_id: str) -> str:
    return next(
        route.vehicle_id for route in plan.routes for stop in route.stops if stop.task_id == task_id
    )


# --- priority ---------------------------------------------------------------------


def test_priority_scale_and_weights_follow_decision_d3() -> None:
    assert dict(PRIORITY_LABELS) == {
        1: "Routine",
        2: "Normal",
        3: "Important",
        4: "High",
        5: "Critical",
    }
    weights = [priority_weight(priority) for priority in range(1, 6)]
    assert weights == [1, 2, 4, 8, 16]
    assert all(lower < higher for lower, higher in pairwise(weights))
    # One Critical task outweighs up to fifteen Routine ones, not sixteen.
    assert 15 * PRIORITY_WEIGHTS[1] < PRIORITY_WEIGHTS[5] <= 16 * PRIORITY_WEIGHTS[1]
    with pytest.raises(ValueError):
        priority_weight(6)


def test_priority_penalties_dwarf_routing_costs_and_cannot_overflow() -> None:
    config = SolverConfig()
    no_env_file: dict[str, Any] = {"_env_file": None}
    settings = Settings(**no_env_file)
    smallest_penalty = config.dropped_task_penalty * min(PRIORITY_WEIGHTS.values())
    # A whole day of routing: every truck-shift used, each driving 5,000 km.
    vehicle_shifts = settings.api_max_tasks  # generous: one shift per task
    routing_cost_bound = vehicle_shifts * (config.vehicle_fixed_cost + 5_000_000)
    assert smallest_penalty * 2 > config.vehicle_fixed_cost + 5_000_000
    # Dropping everything at the highest weight stays far below a signed 64-bit cost.
    largest_total = config.dropped_task_penalty * max(PRIORITY_WEIGHTS.values()) * 2
    assert (largest_total * settings.api_max_tasks + routing_cost_bound) * 1_000 < 2**63


def test_shortage_keeps_the_higher_priorities() -> None:
    plan = _solve(_request(_payload("F")))

    assert plan.status is PlanStatus.PARTIALLY_FEASIBLE
    assert set(plan.scheduled_task_ids) == {"TASK-P5-5", "TASK-P4-4"}
    assert set(plan.unscheduled_task_ids) == {"TASK-P1-1", "TASK-P2-2", "TASK-P3-3", "TASK-P1-6"}
    priorities = {diagnostic.task_id: diagnostic.priority for diagnostic in plan.diagnostics}
    assert priorities == {"TASK-P1-1": 1, "TASK-P2-2": 2, "TASK-P3-3": 3, "TASK-P1-6": 1}
    message = plan.diagnostics[0].message
    assert "not enough fleet time, capacity, or route allowance" in message
    assert "lower-priority" in message
    assert validate_plan_result(_request(_payload("F")), plan).valid


def test_reversed_priorities_keep_the_other_tasks() -> None:
    payload = _payload("F")
    for task in payload["tasks"]:
        task["priority"] = 6 - int(task["priority"])
    plan = _solve(_request(payload))

    kept = {task["task_id"] for task in payload["tasks"] if task["priority"] == 5}
    assert set(plan.scheduled_task_ids) >= kept
    assert len(plan.scheduled_task_ids) == 2
    assert all(
        next(t["priority"] for t in payload["tasks"] if t["task_id"] == task_id) >= 4
        for task_id in plan.scheduled_task_ids
    )


def test_every_task_is_scheduled_when_everything_fits_whatever_the_priority() -> None:
    payload = _payload("F")
    for task in payload["tasks"]:
        task["due_at"] = "2026-12-07T17:00:00"
    payload["vehicle_shifts"][0]["end"] = "2026-12-07T23:00:00"
    payload["tasks"] = payload["tasks"][:4]
    plan = _solve(_request(payload))

    assert plan.status is PlanStatus.FEASIBLE
    assert len(plan.scheduled_task_ids) == 4
    assert plan.diagnostics == ()


def test_pickup_drop_pairs_are_kept_or_dropped_together() -> None:
    payload = _payload("F")
    payload["locations"].append(
        {
            "location_id": "SUPPLIER_X",
            "name": "Supplier X",
            "address": "1 X Road, Toronto, ON",
            "latitude": 43.7,
            "longitude": -79.3,
        }
    )
    matrix = payload["routing_matrix"]
    matrix["location_ids"].append("SUPPLIER_X")
    for row in matrix["distance_meters"]:
        row.append(9_000)
    for row in matrix["duration_seconds"]:
        row.append(900)
    matrix["distance_meters"].append([9_000] * (len(matrix["location_ids"]) - 1) + [0])
    matrix["duration_seconds"].append([900] * (len(matrix["location_ids"]) - 1) + [0])
    for task in payload["tasks"]:
        task["task_type"] = "PICKUP_DROP"
        task["origin_location_id"] = "SUPPLIER_X"
    request = _request(payload)
    plan = _solve(request)

    assert plan.status is PlanStatus.PARTIALLY_FEASIBLE
    for task_id in plan.unscheduled_task_ids:
        assert not any(stop.task_id == task_id for route in plan.routes for stop in route.stops)
    for task_id in plan.scheduled_task_ids:
        kinds = [
            stop.kind for route in plan.routes for stop in route.stops if stop.task_id == task_id
        ]
        assert sorted(kinds) == ["DELIVERY", "PICKUP"]
    assert validate_plan_result(request, plan).valid


# --- vehicle tags -----------------------------------------------------------------


def test_tagged_tasks_go_only_on_trucks_with_the_tags() -> None:
    request = _request(_payload("G"))
    plan = _solve(request)

    assert plan.status is PlanStatus.FEASIBLE
    assert _route_of(plan, "TASK-COLD-1") == "REEFER-1"
    assert _route_of(plan, "TASK-COLD-2") == "REEFER-1"


def test_validator_rejects_a_route_without_the_required_tags() -> None:
    request = _request(_payload("G"))
    plan = _solve(request)
    without_tags = request.model_copy(
        update={
            "vehicles": tuple(
                vehicle.model_copy(update={"tags": frozenset()}) for vehicle in request.vehicles
            )
        }
    )

    verdict = validate_plan_result(without_tags, plan)

    assert not verdict.valid
    assert any("without its required vehicle tags" in issue for issue in verdict.issues)


def test_a_task_no_enabled_truck_can_carry_is_reported_individually() -> None:
    payload = _payload("G")
    payload["tasks"][0]["required_vehicle_tags"] = ["HAZMAT"]
    plan = _solve(_request(payload))

    assert plan.status is PlanStatus.INVALID_INPUT
    diagnostic = next(d for d in plan.diagnostics if d.task_id == "TASK-COLD-1")
    assert diagnostic.code == "NO_COMPATIBLE_VEHICLE"
    assert diagnostic.priority == 2


# --- route duration and distance limits -------------------------------------------


def test_route_limits_put_each_task_on_the_truck_that_can_do_it() -> None:
    request = _request(_payload("H"))
    plan = _solve(request)

    assert plan.status is PlanStatus.FEASIBLE
    assert _route_of(plan, "TASK-FAR") == "SHORT-DAY"
    assert _route_of(plan, "TASK-NEAR") == "LOCAL"
    by_vehicle = {route.vehicle_id: route for route in plan.routes}
    assert by_vehicle["LOCAL"].total_distance_meters <= 60_000
    short_day = by_vehicle["SHORT-DAY"]
    assert short_day.stops[-1].arrival_at - short_day.stops[0].departure_at <= timedelta(
        seconds=9_000
    )
    assert validate_plan_result(request, plan).valid


def test_distance_limit_is_enforced_by_the_solver() -> None:
    unlimited = _request(planning_payload("A"))
    baseline = _solve(unlimited)
    assert max(route.total_distance_meters for route in baseline.routes) > 150_000

    payload = planning_payload("A")
    for vehicle in payload["vehicles"]:
        vehicle["maximum_route_distance_meters"] = 150_000
    request = _request(payload)
    plan = _solve(request)

    assert plan.status is PlanStatus.FEASIBLE
    assert len(plan.routes) > 1
    assert all(route.total_distance_meters <= 150_000 for route in plan.routes)
    assert validate_plan_result(request, plan).valid


def test_validator_rejects_routes_over_the_distance_limit() -> None:
    request = _request(_payload("H"))
    plan = _solve(request)
    tighter = request.model_copy(
        update={
            "vehicles": tuple(
                vehicle.model_copy(update={"maximum_route_distance_meters": 40_000})
                if vehicle.vehicle_id == "LOCAL"
                else vehicle
                for vehicle in request.vehicles
            )
        }
    )

    verdict = validate_plan_result(tighter, plan)

    assert not verdict.valid
    assert any("maximum route distance" in issue for issue in verdict.issues)


@pytest.mark.parametrize("where", ["vehicle", "shift"])
def test_validator_rejects_routes_over_the_duration_limit(where: str) -> None:
    request = _request(_payload("H"))
    plan = _solve(request)
    if where == "vehicle":
        tighter = request.model_copy(
            update={
                "vehicles": tuple(
                    vehicle.model_copy(update={"maximum_route_duration_seconds": 3_600})
                    for vehicle in request.vehicles
                )
            }
        )
    else:
        tighter = request.model_copy(
            update={
                "vehicle_shifts": tuple(
                    shift.model_copy(update={"maximum_route_duration_seconds": 3_600})
                    for shift in request.vehicle_shifts
                )
            }
        )

    verdict = validate_plan_result(tighter, plan)

    assert not verdict.valid
    assert any("maximum route duration" in issue for issue in verdict.issues)


def test_a_task_beyond_every_distance_limit_is_reported_individually() -> None:
    payload = _payload("H")
    payload["vehicles"][0]["enabled"] = False  # only the 60 km truck remains
    plan = _solve(_request(payload))

    assert plan.status is PlanStatus.INFEASIBLE
    diagnostic = next(d for d in plan.diagnostics if d.task_id == "TASK-FAR")
    assert diagnostic.code == "ROUTE_DISTANCE_LIMIT_EXCEEDED"
    assert diagnostic.priority == 1
    assert all(d.task_id != "TASK-NEAR" for d in plan.diagnostics)


def test_without_any_distance_limit_no_distance_dimension_is_added() -> None:
    """Version 1.0 scenarios are solved by exactly the Version 1.0 model."""
    plan = _solve(_request(planning_payload("A")))

    assert plan.status is PlanStatus.FEASIBLE
    assert plan.total_distance_meters == 216_000
    assert [route.vehicle_id for route in plan.routes] == ["TRUCK-1"]


# --- shift depots -----------------------------------------------------------------


def test_multiday_shifts_end_at_their_own_depot() -> None:
    request = _request(_payload("I"))
    plan = _solve(request)

    assert plan.status is PlanStatus.FEASIBLE
    for route in plan.routes:
        expected_end = "HUB_A" if route.vehicle_id == "TRUCK-1" else "PLANT"
        assert route.stops[-1].location_id == expected_end
    assert validate_plan_result(request, plan).valid
