"""M4 capacity and pickup-delivery solver regression tests."""

from __future__ import annotations

from decimal import Decimal

from backend.app.domain import PlanStatus, StopKind, TaskType, validate_planning_payload
from backend.app.domain.models import PlanningRequest
from backend.app.domain.results import PlanResult, PlanRoute, PlanStop
from backend.app.optimization import validate_plan_result
from backend.app.optimization.solver import OrToolsCapacitySolver, SolverConfig
from backend.tests.fixtures.canonical import planning_payload


def _validated_request(scenario_letter: str) -> PlanningRequest:
    result = validate_planning_payload(planning_payload(scenario_letter))
    assert result.valid, result.issues
    assert result.normalized_request is not None
    return result.normalized_request


def _first_shift_day_request(
    request: PlanningRequest,
    *,
    vehicle_ids: tuple[str, ...],
    task_ids: tuple[str, ...],
) -> PlanningRequest:
    vehicle_id_set = set(vehicle_ids)
    task_id_set = set(task_ids)
    first_shift_date = min(shift.start.date() for shift in request.vehicle_shifts)
    return request.model_copy(
        update={
            "vehicles": tuple(
                vehicle for vehicle in request.vehicles if vehicle.vehicle_id in vehicle_id_set
            ),
            "vehicle_shifts": tuple(
                shift
                for shift in request.vehicle_shifts
                if shift.vehicle_id in vehicle_id_set and shift.start.date() == first_shift_date
            ),
            "tasks": tuple(task for task in request.tasks if task.task_id in task_id_set),
        }
    )


def _solve(request: PlanningRequest) -> PlanResult:
    return OrToolsCapacitySolver(SolverConfig(time_limit_seconds=2)).solve(request)


def _task_stops(result: PlanResult, task_id: str) -> tuple[tuple[PlanRoute, PlanStop], ...]:
    return tuple(
        (route, stop) for route in result.routes for stop in route.stops if stop.task_id == task_id
    )


def _assert_valid_feasible_plan(request: PlanningRequest, result: PlanResult) -> None:
    assert result.status is PlanStatus.FEASIBLE
    validation = validate_plan_result(request, result)
    assert validation.valid, validation.issues


def test_one_truck_one_pickup_is_scheduled_pickup_then_plant_delivery() -> None:
    request = _first_shift_day_request(
        _validated_request("A"),
        vehicle_ids=("TRUCK-1",),
        task_ids=("TASK-PICK-001",),
    )

    result = _solve(request)

    _assert_valid_feasible_plan(request, result)
    stops = _task_stops(result, "TASK-PICK-001")
    assert [(stop.kind, stop.location_id) for _, stop in stops] == [
        (StopKind.PICKUP, "SUPPLIER_A"),
        (StopKind.DELIVERY, "PLANT"),
    ]
    assert result.routes[0].stops[0].kind is StopKind.DEPOT_START
    assert result.routes[0].stops[-1].kind is StopKind.DEPOT_END


def test_one_truck_one_drop_loads_at_plant_before_customer_delivery() -> None:
    request = _first_shift_day_request(
        _validated_request("A"),
        vehicle_ids=("TRUCK-1",),
        task_ids=("TASK-DROP-001",),
    )

    result = _solve(request)

    _assert_valid_feasible_plan(request, result)
    stops = _task_stops(result, "TASK-DROP-001")
    assert [(stop.kind, stop.location_id, stop.load_after) for _, stop in stops] == [
        (StopKind.PICKUP, "PLANT", Decimal("5")),
        (StopKind.DELIVERY, "CUSTOMER_A", Decimal("0")),
    ]


def test_pickup_drop_pair_stays_on_same_route_with_pickup_before_delivery() -> None:
    request = _first_shift_day_request(
        _validated_request("E"),
        vehicle_ids=("TRUCK-1", "TRUCK-2"),
        task_ids=("TASK-PAIR-PRECEDENCE",),
    )

    result = _solve(request)

    _assert_valid_feasible_plan(request, result)
    stops = _task_stops(result, "TASK-PAIR-PRECEDENCE")
    assert len({route.shift_id for route, _ in stops}) == 1
    assert [(stop.kind, stop.location_id) for _, stop in stops] == [
        (StopKind.PICKUP, "SUPPLIER_A"),
        (StopKind.DELIVERY, "CUSTOMER_A"),
    ]


def test_mixed_task_types_across_three_available_trucks_are_all_scheduled_once() -> None:
    request = _first_shift_day_request(
        _validated_request("A"),
        vehicle_ids=("TRUCK-1", "TRUCK-2", "TRUCK-3"),
        task_ids=(
            "TASK-PICK-001",
            "TASK-PICK-002",
            "TASK-DROP-001",
            "TASK-DROP-002",
            "TASK-PAIR-001",
            "TASK-PAIR-002",
        ),
    )

    result = _solve(request)

    _assert_valid_feasible_plan(request, result)
    assert result.scheduled_task_ids == tuple(task.task_id for task in request.tasks)
    scheduled_types = {
        task.task_type for task in request.tasks if task.task_id in result.scheduled_task_ids
    }
    assert scheduled_types == {TaskType.PICKUP, TaskType.DROP, TaskType.PICKUP_DROP}
    for task in request.tasks:
        stops = _task_stops(result, task.task_id)
        assert [stop.kind for _, stop in stops] == [StopKind.PICKUP, StopKind.DELIVERY]


def test_load_never_drops_below_zero_or_exceeds_assigned_vehicle_capacity() -> None:
    request = _first_shift_day_request(
        _validated_request("A"),
        vehicle_ids=("TRUCK-1", "TRUCK-2", "TRUCK-3"),
        task_ids=(
            "TASK-PICK-001",
            "TASK-DROP-002",
            "TASK-PAIR-002",
        ),
    )

    result = _solve(request)

    _assert_valid_feasible_plan(request, result)
    capacity_by_vehicle = {vehicle.vehicle_id: vehicle.capacity for vehicle in request.vehicles}
    for route in result.routes:
        for stop in route.stops:
            assert Decimal(0) <= stop.load_after <= capacity_by_vehicle[route.vehicle_id]


def test_quantity_equal_to_vehicle_capacity_is_feasible() -> None:
    base = _first_shift_day_request(
        _validated_request("E"),
        vehicle_ids=("TRUCK-1",),
        task_ids=("TASK-PAIR-PRECEDENCE",),
    )
    request = base.model_copy(
        update={
            "vehicles": (base.vehicles[0].model_copy(update={"capacity": Decimal("4")}),),
        }
    )

    result = _solve(request)

    _assert_valid_feasible_plan(request, result)
    assert result.routes[0].peak_load == Decimal("4")


def test_quantity_above_all_vehicle_capacities_is_rejected_before_solving() -> None:
    base = _first_shift_day_request(
        _validated_request("E"),
        vehicle_ids=("TRUCK-1",),
        task_ids=("TASK-PAIR-PRECEDENCE",),
    )
    request = base.model_copy(
        update={
            "vehicles": (base.vehicles[0].model_copy(update={"capacity": Decimal("3")}),),
        }
    )

    result = _solve(request)

    assert result.status is PlanStatus.INVALID_INPUT
    assert result.routes == ()
    assert result.unscheduled_task_ids == ("TASK-PAIR-PRECEDENCE",)
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["CAPACITY_EXCEEDED"]


def test_start_end_depots_and_reported_totals_are_consistent() -> None:
    request = _first_shift_day_request(
        _validated_request("A"),
        vehicle_ids=("TRUCK-1",),
        task_ids=("TASK-DROP-001",),
    )

    result = _solve(request)

    _assert_valid_feasible_plan(request, result)
    route = result.routes[0]
    assert route.stops[0].node_id == f"{route.shift_id}::start"
    assert route.stops[-1].node_id == f"{route.shift_id}::end"
    assert route.stops[0].location_id == "PLANT"
    assert route.stops[-1].location_id == "PLANT"
    assert route.total_distance_meters == sum(
        stop.distance_from_previous_meters for stop in route.stops
    )
    assert route.driving_seconds == sum(stop.duration_from_previous_seconds for stop in route.stops)
    assert result.total_distance_meters == route.total_distance_meters
    assert result.total_driving_seconds == route.driving_seconds
    assert result.total_service_seconds == route.service_seconds
    assert result.total_waiting_seconds == route.waiting_seconds


def test_solver_is_stable_for_repeated_core_runs() -> None:
    request = _first_shift_day_request(
        _validated_request("A"),
        vehicle_ids=("TRUCK-1",),
        task_ids=("TASK-PICK-001", "TASK-DROP-001"),
    )

    first = _solve(request)
    second = _solve(request)

    _assert_valid_feasible_plan(request, first)
    _assert_valid_feasible_plan(request, second)
    first_signature = tuple(
        (route.shift_id, tuple(stop.node_id for stop in route.stops)) for route in first.routes
    )
    second_signature = tuple(
        (route.shift_id, tuple(stop.node_id for stop in route.stops)) for route in second.routes
    )
    assert first_signature == second_signature


def test_result_validator_rejects_corrupted_capacity_state() -> None:
    request = _first_shift_day_request(
        _validated_request("A"),
        vehicle_ids=("TRUCK-1",),
        task_ids=("TASK-DROP-001",),
    )
    result = _solve(request)
    _assert_valid_feasible_plan(request, result)
    route = result.routes[0]
    corrupted_stop = route.stops[1].model_copy(update={"load_after": Decimal("999")})
    corrupted_route = route.model_copy(
        update={"stops": (route.stops[0], corrupted_stop, *route.stops[2:])}
    )
    corrupted_result = result.model_copy(update={"routes": (corrupted_route,)})

    validation = validate_plan_result(request, corrupted_result)

    assert not validation.valid
    assert any("load" in issue or "capacity" in issue for issue in validation.issues)
