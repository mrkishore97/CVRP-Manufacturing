"""V1.1-M5 optimization options (plan §10.1 to §10.3, §10.6, §10.8).

- No options gives Version 1.0's plans; precomputed matrices change nothing.
- Fixture V11-E: fewest trucks uses the fewest truck-shifts; balanced uses more and has a
  shorter longest route; least travel drives no more than the other two. Balance presets
  are frozen here.
- Every mode and search effort passes the independent validator on every fixture.
- The travel-time buffer is seen identically by solver, pre-check, and validator.
- Thorough search stays within its time limit and is never worse than standard.
- Timeouts are still told apart from infeasibility.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

import pytest

from backend.app.application.planning_service import (
    PlanningService,
    apply_travel_time_factor,
    new_plan_id,
)
from backend.app.domain import PlanStatus, validate_planning_payload
from backend.app.domain.enums import ObjectiveMode, SearchEffort
from backend.app.domain.models import PlanningRequest
from backend.app.domain.options import OptimizationOptions
from backend.app.domain.results import PlanResult
from backend.app.optimization import validate_plan_result
from backend.app.optimization.objective import (
    BALANCE_SPAN_COEFFICIENTS,
    VERSION_1_0_VEHICLE_FIXED_COST,
    solve_settings,
)
from backend.app.optimization.solver import OrToolsCapacitySolver, SolverConfig
from backend.tests.fixtures.canonical import planning_payload

V1_1_DIR = Path(__file__).resolve().parents[4] / "sample_data" / "v1_1"
V1_1_FIXTURES = (
    "v11_e_objective_modes.json",
    "v11_f_priority_shortage.json",
    "v11_g_vehicle_tags.json",
    "v11_h_route_limits.json",
    "v11_i_multiday_shift_depots.json",
)
CANONICAL = ("A", "C", "D", "E", "F")
MODES = tuple(ObjectiveMode)
EFFORTS = tuple(SearchEffort)


def _fixture(name: str) -> dict[str, Any]:
    with (V1_1_DIR / name).open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def _v11e(**options: Any) -> dict[str, Any]:
    payload = _fixture("v11_e_objective_modes.json")
    if options:
        payload["optimization_options"] = options
    return payload


def _request(payload: dict[str, Any]) -> PlanningRequest:
    result = validate_planning_payload(payload)
    assert result.valid, result.issues
    assert result.normalized_request is not None
    return result.normalized_request


def _plan(payload: dict[str, Any]) -> PlanResult:
    return PlanningService().optimize(_request(payload))


def _all_payloads() -> list[tuple[str, dict[str, Any]]]:
    payloads = [(letter, planning_payload(letter)) for letter in CANONICAL]
    payloads += [(name, _fixture(name)) for name in V1_1_FIXTURES]
    return payloads


# --- Version 1.0 behaviour --------------------------------------------------------


@pytest.mark.parametrize("letter", CANONICAL)
def test_default_options_reproduce_the_version_1_0_solve(letter: str) -> None:
    request = _request(planning_payload(letter))
    version_1_0 = OrToolsCapacitySolver().solve(request)
    with_service = PlanningService().optimize(request)

    assert with_service.status is version_1_0.status
    assert with_service.routes == version_1_0.routes
    assert with_service.total_distance_meters == version_1_0.total_distance_meters
    assert solve_settings(OptimizationOptions(), 10).vehicle_fixed_cost == (
        VERSION_1_0_VEHICLE_FIXED_COST
    )


@pytest.mark.parametrize("letter", CANONICAL)
def test_precomputed_matrices_and_callbacks_give_identical_plans(letter: str) -> None:
    request = _request(planning_payload(letter))
    matrices = OrToolsCapacitySolver(SolverConfig()).solve(request)
    callbacks = OrToolsCapacitySolver(SolverConfig(transit_matrix_max_nodes=0)).solve(request)

    assert matrices.status is callbacks.status
    assert matrices.routes == callbacks.routes
    assert matrices.scheduled_task_ids == callbacks.scheduled_task_ids


# --- objective modes on V11-E -----------------------------------------------------


def test_fixture_v11_e_objective_modes_differ_as_documented() -> None:
    trucks = _plan(_v11e(objective_mode="MINIMIZE_TRUCKS"))
    travel = _plan(_v11e(objective_mode="MINIMIZE_TRAVEL"))
    balanced = _plan(_v11e(objective_mode="BALANCE_WORKLOAD"))
    plans = (trucks, travel, balanced)
    assert all(plan.status is PlanStatus.FEASIBLE for plan in plans)
    assert trucks.metrics and travel.metrics and balanced.metrics

    assert trucks.metrics.truck_shifts_used == 1
    assert trucks.metrics.truck_shifts_used == min(
        plan.metrics.truck_shifts_used for plan in plans if plan.metrics
    )
    assert balanced.metrics.truck_shifts_used > trucks.metrics.truck_shifts_used
    assert balanced.metrics.longest_working_seconds < trucks.metrics.longest_working_seconds
    assert balanced.metrics.longest_route_seconds < trucks.metrics.longest_route_seconds
    assert travel.total_distance_meters <= trucks.total_distance_meters
    assert travel.total_distance_meters <= balanced.total_distance_meters


def test_balance_presets_are_frozen() -> None:
    """Changing a preset changes plans; this records what each gives on V11-E."""
    assert dict(BALANCE_SPAN_COEFFICIENTS) == {"LIGHT": 5, "MEDIUM": 10, "STRONG": 20}
    observed = {}
    for strength in ("LIGHT", "MEDIUM", "STRONG"):
        plan = _plan(_v11e(objective_mode="BALANCE_WORKLOAD", balance_strength=strength))
        assert plan.metrics is not None
        observed[strength] = (
            plan.metrics.truck_shifts_used,
            plan.total_distance_meters,
            plan.metrics.longest_working_seconds,
        )
    assert observed == {
        "LIGHT": (2, 229_000, observed["LIGHT"][2]),
        "MEDIUM": (3, 254_000, observed["MEDIUM"][2]),
        "STRONG": (3, 288_000, observed["STRONG"][2]),
    }
    working = [observed[strength][2] for strength in ("LIGHT", "MEDIUM", "STRONG")]
    assert working == sorted(working, reverse=True)
    assert round(working[0] / 3600, 2) == 4.14
    assert round(working[1] / 3600, 2) == 3.39
    assert round(working[2] / 3600, 2) == 3.11


def test_cost_of_an_extra_truck_changes_fewest_trucks() -> None:
    cheap = _plan(_v11e(objective_mode="MINIMIZE_TRUCKS", extra_truck_cost_km=0))
    default = _plan(_v11e(objective_mode="MINIMIZE_TRUCKS"))

    assert cheap.total_distance_meters <= default.total_distance_meters
    assert solve_settings(OptimizationOptions(extra_truck_cost_km=250), 5).vehicle_fixed_cost == (
        250_000
    )


# --- every mode and effort is valid -----------------------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("effort", EFFORTS)
def test_every_mode_and_effort_passes_the_independent_validator(
    mode: ObjectiveMode, effort: SearchEffort
) -> None:
    for name, payload in _all_payloads():
        payload["optimization_options"] = {
            "objective_mode": mode.value,
            "search_effort": effort.value,
            "time_limit_seconds": 1,
        }
        request = _request(payload)
        plan = PlanningService().optimize(request)

        assert plan.status is not PlanStatus.INTERNAL_ERROR, (name, plan.warnings)
        if plan.routes:
            assert validate_plan_result(request, plan).valid, name
        assert plan.optimization_options is not None
        assert plan.optimization_options.objective_mode is mode


# --- travel-time buffer -----------------------------------------------------------


def _one_drop(factor: float, due: str = "2026-06-22T08:05:00-04:00") -> dict[str, Any]:
    payload = _v11e(travel_time_factor=factor)
    payload["tasks"] = [task for task in payload["tasks"] if task["task_id"] == "TASK-DROP-001"]
    payload["tasks"][0]["due_at"] = due
    return payload


def test_buffer_deadline_holds_at_1_0_and_is_diagnosed_at_1_5() -> None:
    # Plant to customer A: 15 min loading, 25 min driving, 20 min unloading = 08:00.
    holds = _plan(_one_drop(1.0))
    fails = _plan(_one_drop(1.5))

    assert holds.status is PlanStatus.FEASIBLE
    assert fails.status is PlanStatus.INFEASIBLE
    [diagnostic] = fails.diagnostics
    assert diagnostic.code == "DEADLINE_IMPOSSIBLE_INDIVIDUALLY"
    assert diagnostic.estimated_completion_at is not None
    assert diagnostic.due_at is not None
    assert diagnostic.estimated_completion_at - diagnostic.due_at == timedelta(
        minutes=7, seconds=30
    )


def test_solver_precheck_and_validator_see_the_same_buffered_times() -> None:
    request = _request(_one_drop(1.2, due="2026-06-22T12:00:00-04:00"))
    plan = PlanningService().optimize(request)
    buffered = apply_travel_time_factor(request, 1.2)

    assert plan.status is PlanStatus.FEASIBLE
    legs = [stop.duration_from_previous_seconds for route in plan.routes for stop in route.stops]
    assert 1_800 in legs  # 1,500 s at 1.2
    assert validate_plan_result(buffered, plan).valid
    assert not validate_plan_result(request, plan).valid  # unbuffered times disagree
    assert request.routing_matrix is not None
    assert request.routing_matrix.duration_seconds[0][3] == 1_500  # stored matrix untouched
    assert plan.matrix is not None and plan.matrix.travel_time_factor == 1.2


def test_buffer_rounds_each_leg_and_leaves_a_factor_of_one_alone() -> None:
    request = _request(_v11e())
    assert apply_travel_time_factor(request, 1.0) is request
    scaled = apply_travel_time_factor(request, 1.25)
    assert scaled.routing_matrix is not None
    assert scaled.routing_matrix.duration_seconds[0][1] == 2_250


# --- search effort, time limit, and timeouts --------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_thorough_search_respects_the_time_limit_and_is_no_worse(mode: ObjectiveMode) -> None:
    standard = _plan(_v11e(objective_mode=mode.value, time_limit_seconds=2))
    started = perf_counter()
    thorough = _plan(
        _v11e(objective_mode=mode.value, search_effort="THOROUGH", time_limit_seconds=2)
    )
    elapsed = perf_counter() - started

    assert elapsed <= 2 + 1.5
    assert thorough.status is PlanStatus.FEASIBLE
    assert standard.metrics and thorough.metrics
    assert standard.metrics.objective_value is not None
    assert thorough.metrics.objective_value is not None
    assert thorough.metrics.objective_value <= standard.metrics.objective_value


def test_thorough_search_on_a_shortage_is_still_a_partial_plan_not_a_timeout() -> None:
    payload = _fixture("v11_f_priority_shortage.json")
    payload["optimization_options"] = {"search_effort": "THOROUGH", "time_limit_seconds": 1}
    plan = _plan(payload)

    assert plan.status is PlanStatus.PARTIALLY_FEASIBLE
    assert set(plan.scheduled_task_ids) == {"TASK-P4-4", "TASK-P5-5"}


def test_time_limit_defaults_to_the_server_and_is_capped_by_it() -> None:
    service = PlanningService(default_time_limit_seconds=7, max_time_limit_seconds=30)

    assert service.effective_time_limit(OptimizationOptions()) == 7
    assert service.effective_time_limit(OptimizationOptions(time_limit_seconds=12)) == 12
    assert service.effective_time_limit(OptimizationOptions(time_limit_seconds=300)) == 30
    plan = service.optimize(_request(_v11e()))
    assert plan.optimization_options is not None
    assert plan.optimization_options.time_limit_seconds == 7


# --- plan identity and metadata ---------------------------------------------------


def test_each_plan_gets_a_unique_short_id_and_its_metadata() -> None:
    request = _request(_v11e(objective_mode="BALANCE_WORKLOAD"))
    first = PlanningService().optimize(request)
    second = PlanningService().optimize(request)

    assert first.plan_id != second.plan_id
    assert first.plan_id.startswith("PLAN-") and len(first.plan_id) == len("PLAN-") + 16 + 1 + 8
    assert first.created_at is not None
    assert first.matrix is not None and first.matrix.location_count == 7
    assert first.matrix.source == "deterministic_offline_fixture"
    assert first.metrics is not None
    assert first.metrics.truck_shifts_used == len(first.routes)
    assert first.metrics.truck_shifts_available == 3
    assert first.metrics.longest_route_seconds >= first.metrics.shortest_route_seconds > 0
    assert 0 < first.metrics.load_utilisation <= 1
    assert 0 < first.metrics.time_utilisation <= 1
    for route in first.routes:
        assert route.total_duration_seconds == int(
            (route.stops[-1].arrival_at - route.stops[0].departure_at).total_seconds()
        )
    long_scenario = "S" * 120
    assert len(new_plan_id(long_scenario, first.created_at)) == 30


def test_plans_stored_by_version_1_0_stay_readable() -> None:
    stored = {
        "plan_id": "A:M5",
        "status": "FEASIBLE",
        "routes": [],
        "diagnostics": [],
        "scheduled_task_ids": [],
        "unscheduled_task_ids": [],
        "total_distance_meters": 0,
        "solver_elapsed_seconds": 0.1,
    }
    plan = PlanResult.model_validate(stored)

    assert plan.metrics is None and plan.optimization_options is None and plan.created_at is None


def test_validator_rejects_a_wrong_route_duration() -> None:
    request = _request(_v11e())
    plan = PlanningService().optimize(request)
    route = plan.routes[0]
    broken = plan.model_copy(
        update={
            "routes": (
                route.model_copy(
                    update={"total_duration_seconds": (route.total_duration_seconds or 0) + 60}
                ),
            )
        }
    )

    assert any(
        "total duration is inconsistent" in issue
        for issue in validate_plan_result(request, broken).issues
    )
