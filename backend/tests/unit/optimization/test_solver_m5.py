"""M5 time-window, shift, and diagnostic solver regression tests."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from backend.app.domain import PlanStatus, StopKind, validate_planning_payload
from backend.app.domain.models import PlanningRequest, Task, VehicleShift
from backend.app.domain.results import PlanResult, PlanRoute, PlanStop
from backend.app.optimization import validate_plan_result
from backend.app.optimization.solver import (
    OrToolsCapacitySolver,
    SolverConfig,
    _routing_failure_status,
)
from backend.tests.fixtures.canonical import planning_payload


def _validated_request(scenario_letter: str) -> PlanningRequest:
    result = validate_planning_payload(planning_payload(scenario_letter))
    assert result.valid, result.issues
    assert result.normalized_request is not None
    return result.normalized_request


def _solve(request: PlanningRequest) -> PlanResult:
    return OrToolsCapacitySolver(SolverConfig(time_limit_seconds=2)).solve(request)


def _task_stops(result: PlanResult, task_id: str) -> tuple[tuple[PlanRoute, PlanStop], ...]:
    return tuple(
        (route, stop) for route in result.routes for stop in route.stops if stop.task_id == task_id
    )


def _single_task_request(request: PlanningRequest, task_id: str) -> PlanningRequest:
    return request.model_copy(
        update={
            "vehicles": (request.vehicles[0],),
            "vehicle_shifts": (request.vehicle_shifts[0],),
            "tasks": tuple(task for task in request.tasks if task.task_id == task_id),
        }
    )


def _replace_task(request: PlanningRequest, replacement: Task) -> PlanningRequest:
    return request.model_copy(
        update={
            "tasks": tuple(
                replacement if task.task_id == replacement.task_id else task
                for task in request.tasks
            )
        }
    )


def _replace_shift(request: PlanningRequest, replacement: VehicleShift) -> PlanningRequest:
    return request.model_copy(
        update={
            "vehicle_shifts": tuple(
                replacement if shift.shift_id == replacement.shift_id else shift
                for shift in request.vehicle_shifts
            )
        }
    )


def _assert_valid_strict_or_partial(request: PlanningRequest, result: PlanResult) -> None:
    validation = validate_plan_result(request, result)
    assert validation.valid, validation.issues


def test_waiting_is_inserted_when_truck_arrives_before_ready_time() -> None:
    request = _single_task_request(_validated_request("A"), "TASK-PICK-002")
    task = request.tasks[0]
    expected_arrival = request.vehicle_shifts[0].start + timedelta(seconds=2_400)

    result = _solve(request)

    assert result.status is PlanStatus.FEASIBLE
    _assert_valid_strict_or_partial(request, result)
    pickup_stop = next(
        stop for _, stop in _task_stops(result, task.task_id) if stop.kind is StopKind.PICKUP
    )
    assert pickup_stop.arrival_at == expected_arrival
    assert pickup_stop.service_start_at == task.ready_at
    assert result.routes[0].waiting_seconds == 1_200


def test_exact_completion_deadline_boundary_is_feasible_with_zero_slack() -> None:
    request = _single_task_request(_validated_request("A"), "TASK-PICK-001")
    exact_completion = request.vehicle_shifts[0].start + timedelta(seconds=5_300)
    task = request.tasks[0].model_copy(update={"due_at": exact_completion})
    request = _replace_task(request, task)

    result = _solve(request)

    assert result.status is PlanStatus.FEASIBLE
    _assert_valid_strict_or_partial(request, result)
    delivery_stop = next(
        stop for _, stop in _task_stops(result, task.task_id) if stop.kind is StopKind.DELIVERY
    )
    assert delivery_stop.departure_at == exact_completion
    assert delivery_stop.slack_seconds == 0


def test_one_second_deadline_miss_is_infeasible_before_solving() -> None:
    request = _single_task_request(_validated_request("A"), "TASK-PICK-001")
    exact_completion = request.vehicle_shifts[0].start + timedelta(seconds=5_300)
    task = request.tasks[0].model_copy(update={"due_at": exact_completion - timedelta(seconds=1)})
    request = _replace_task(request, task)

    result = _solve(request)

    assert result.status is PlanStatus.INFEASIBLE
    assert result.routes == ()
    assert result.unscheduled_task_ids == (task.task_id,)
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "DEADLINE_IMPOSSIBLE_INDIVIDUALLY"
    ]
    assert result.diagnostics[0].late_by_seconds == 1


def test_service_time_is_included_in_deadline_completion() -> None:
    request = _single_task_request(_validated_request("A"), "TASK-PICK-001")
    delivery_arrival_before_service = request.vehicle_shifts[0].start + timedelta(seconds=4_400)
    task = request.tasks[0].model_copy(update={"due_at": delivery_arrival_before_service})
    request = _replace_task(request, task)

    result = _solve(request)

    assert result.status is PlanStatus.INFEASIBLE
    assert result.diagnostics[0].code == "DEADLINE_IMPOSSIBLE_INDIVIDUALLY"
    assert result.diagnostics[0].late_by_seconds == 900


def test_route_cannot_exceed_shift_end() -> None:
    request = _single_task_request(_validated_request("A"), "TASK-PICK-001")
    route_completion = request.vehicle_shifts[0].start + timedelta(seconds=5_300)
    short_shift = request.vehicle_shifts[0].model_copy(
        update={"end": route_completion - timedelta(seconds=1)}
    )
    request = _replace_shift(request, short_shift)

    result = _solve(request)

    assert result.status is PlanStatus.INFEASIBLE
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["NO_COMPATIBLE_SHIFT_TIME"]


def test_task_moves_to_next_compatible_day_when_due_date_permits() -> None:
    request = _validated_request("F")

    result = _solve(request)

    assert result.status is PlanStatus.FEASIBLE
    _assert_valid_strict_or_partial(request, result)
    assignment_by_task = {
        stop.task_id: route.shift_id
        for route in result.routes
        for stop in route.stops
        if stop.kind is StopKind.PICKUP and stop.task_id is not None
    }
    assert assignment_by_task == {
        "TASK-DAY-1": "TRUCK-1-20260622",
        "TASK-DAY-2": "TRUCK-1-20260623",
    }


def test_task_cannot_move_to_a_later_shift_past_due_date() -> None:
    base = _validated_request("A")
    request = base.model_copy(
        update={
            "vehicles": (base.vehicles[0],),
            "vehicle_shifts": (base.vehicle_shifts[3],),
            "tasks": tuple(task for task in base.tasks if task.task_id == "TASK-PICK-001"),
        }
    )

    result = _solve(request)

    assert result.status is PlanStatus.INFEASIBLE
    assert result.diagnostics[0].code == "DEADLINE_IMPOSSIBLE_INDIVIDUALLY"


def test_physical_truck_is_not_double_booked_across_dated_shifts() -> None:
    request = _validated_request("F")

    result = _solve(request)

    assert result.status is PlanStatus.FEASIBLE
    assert {route.vehicle_id for route in result.routes} == {"TRUCK-1"}
    assert {route.shift_id for route in result.routes} == {
        "TRUCK-1-20260622",
        "TRUCK-1-20260623",
    }
    for route in result.routes:
        shift = next(shift for shift in request.vehicle_shifts if shift.shift_id == route.shift_id)
        assert route.stops[0].arrival_at == shift.start
        assert route.stops[-1].departure_at <= shift.end


def test_scenario_c_reports_individually_impossible_deadline_with_estimate() -> None:
    request = _validated_request("C")

    result = _solve(request)

    assert result.status is PlanStatus.INFEASIBLE
    assert result.unscheduled_task_ids == ("TASK-DEADLINE-001",)
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "DEADLINE_IMPOSSIBLE_INDIVIDUALLY"
    ]
    assert result.diagnostics[0].estimated_completion_at is not None
    assert result.diagnostics[0].late_by_seconds == 2_000


def test_scenario_d_returns_partial_plan_for_collective_fleet_shortage() -> None:
    request = _validated_request("D")

    result = _solve(request)

    assert result.status is PlanStatus.PARTIALLY_FEASIBLE
    _assert_valid_strict_or_partial(request, result)
    assert len(result.scheduled_task_ids) >= 3
    assert len(result.unscheduled_task_ids) >= 1
    assert {diagnostic.code for diagnostic in result.diagnostics} == {
        "INSUFFICIENT_COMBINED_FLEET_TIME"
    }
    for route in result.routes:
        assert route.peak_load <= Decimal("10")
        for stop in route.stops:
            if stop.due_at is not None:
                assert stop.slack_seconds is not None and stop.slack_seconds >= 0


def test_relaxed_diagnostic_drops_paired_nodes_together() -> None:
    request = _validated_request("D")

    result = _solve(request)

    routed_unscheduled_stops = [
        stop
        for route in result.routes
        for stop in route.stops
        if stop.task_id in result.unscheduled_task_ids
    ]
    assert result.status is PlanStatus.PARTIALLY_FEASIBLE
    assert routed_unscheduled_stops == []


def test_solver_timeout_status_is_not_reported_as_proven_infeasible() -> None:
    assert _routing_failure_status(timed_out=True) is PlanStatus.TIMEOUT
    assert _routing_failure_status(timed_out=False) is PlanStatus.INFEASIBLE
