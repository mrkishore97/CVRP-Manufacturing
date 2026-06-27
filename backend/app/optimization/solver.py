"""OR-Tools based capacity, time-window, and pickup-delivery route solver."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Final

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from backend.app.domain.enums import PlanStatus, StopKind
from backend.app.domain.models import (
    PlanningRequest,
    RoutingMatrix,
    Vehicle,
    VehicleShift,
)
from backend.app.domain.results import PlanResult, PlanRoute, PlanStop, TaskDiagnostic
from backend.app.optimization.task_expander import ExpandedTask, ExpandedTaskNode, expand_tasks
from backend.app.optimization.validator import validate_plan_result

_LOAD_SCALE: Final = Decimal("1000")
_ROUTING_FAIL_TIMEOUT: Final = 4


@dataclass(frozen=True, slots=True)
class SolverConfig:
    """Deterministic solver controls for the backend route optimizer."""

    time_limit_seconds: int = 10
    vehicle_fixed_cost: int = 1_000_000
    dropped_task_penalty: int = 100_000_000

    def __post_init__(self) -> None:
        if self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be positive")
        if self.vehicle_fixed_cost < 0:
            raise ValueError("vehicle_fixed_cost must be non-negative")
        if self.dropped_task_penalty <= 0:
            raise ValueError("dropped_task_penalty must be positive")


@dataclass(frozen=True, slots=True)
class _SolverNode:
    node_id: str
    kind: StopKind
    location_id: str
    load_delta_units: int = 0
    load_delta: Decimal = Decimal(0)
    service_seconds: int = 0
    task_id: str | None = None
    ready_at: datetime | None = None
    completion_due_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class _ProblemData:
    nodes: tuple[_SolverNode, ...]
    active_shifts: tuple[VehicleShift, ...]
    vehicles_by_shift: tuple[Vehicle, ...]
    starts: tuple[int, ...]
    ends: tuple[int, ...]
    pairs: tuple[ExpandedTask, ...]
    pair_node_indices: dict[str, tuple[int, int]]
    compatible_vehicle_indices: dict[str, tuple[int, ...]]
    location_index: dict[str, int]
    horizon_start: datetime
    max_time_seconds: int


@dataclass(frozen=True, slots=True)
class _SolveAttempt:
    assignment: pywrapcp.Assignment | None
    manager: pywrapcp.RoutingIndexManager
    routing: pywrapcp.RoutingModel
    elapsed_seconds: float
    timed_out: bool


@dataclass(frozen=True, slots=True)
class _TaskTiming:
    event_completion_at: datetime
    route_end_at: datetime


def _load_units(value: Decimal) -> int:
    return int((value * _LOAD_SCALE).to_integral_exact())


def _load_decimal(units: int) -> Decimal:
    return Decimal(units) / _LOAD_SCALE


def _diagnostic(
    *,
    code: str,
    message: str,
    task_id: str = "REQUEST",
    po_number: str = "REQUEST",
    due_at: datetime | None = None,
) -> TaskDiagnostic:
    return TaskDiagnostic(
        task_id=task_id,
        po_number=po_number,
        code=code,
        message=message,
        due_at=due_at,
    )


def _task_diagnostic(code: str, message: str, task_id: str, po_number: str) -> TaskDiagnostic:
    return _diagnostic(code=code, message=message, task_id=task_id, po_number=po_number)


def _deadline_diagnostic(
    *,
    code: str,
    message: str,
    task_id: str,
    po_number: str,
    due_at: datetime,
    estimated_completion_at: datetime | None,
) -> TaskDiagnostic:
    late_by_seconds = None
    if estimated_completion_at is not None and estimated_completion_at > due_at:
        late_by_seconds = int((estimated_completion_at - due_at).total_seconds())
    return TaskDiagnostic(
        task_id=task_id,
        po_number=po_number,
        code=code,
        message=message,
        due_at=due_at,
        estimated_completion_at=estimated_completion_at,
        late_by_seconds=late_by_seconds,
    )


def _route_duration_limit_seconds(vehicle: Vehicle, shift: VehicleShift) -> int:
    limit = int((shift.end - shift.start).total_seconds())
    if vehicle.maximum_route_duration_seconds is not None:
        limit = min(limit, vehicle.maximum_route_duration_seconds)
    if shift.maximum_route_duration_seconds is not None:
        limit = min(limit, shift.maximum_route_duration_seconds)
    return limit


def _matrix_lookup(matrix: RoutingMatrix) -> dict[str, int]:
    return {location_id: index for index, location_id in enumerate(matrix.location_ids)}


def _seconds_from_horizon(data: _ProblemData, value: datetime) -> int:
    return int((value.astimezone(UTC) - data.horizon_start).total_seconds())


def _routing_failure_status(*, timed_out: bool) -> PlanStatus:
    return PlanStatus.TIMEOUT if timed_out else PlanStatus.INFEASIBLE


def _travel_distance(
    data: _ProblemData,
    matrix: RoutingMatrix,
    from_node: int,
    to_node: int,
) -> int:
    origin = data.location_index[data.nodes[from_node].location_id]
    destination = data.location_index[data.nodes[to_node].location_id]
    return matrix.distance_meters[origin][destination]


def _travel_duration(
    data: _ProblemData,
    matrix: RoutingMatrix,
    from_node: int,
    to_node: int,
) -> int:
    origin = data.location_index[data.nodes[from_node].location_id]
    destination = data.location_index[data.nodes[to_node].location_id]
    return matrix.duration_seconds[origin][destination]


class OrToolsCapacitySolver:
    """Solve tasks with hard capacity, time-window, pairing, order, and depot constraints."""

    def __init__(self, config: SolverConfig | None = None) -> None:
        self._config = config or SolverConfig()

    def solve(self, request: PlanningRequest) -> PlanResult:
        """Return a validated route plan or a controlled infeasibility/diagnostic result."""
        started = perf_counter()
        static_diagnostics = self._static_precheck(request)
        if static_diagnostics:
            return self._failure_result(
                request,
                PlanStatus.INVALID_INPUT,
                static_diagnostics,
                elapsed_seconds=perf_counter() - started,
            )
        if request.routing_matrix is None:
            return self._failure_result(
                request,
                PlanStatus.INVALID_INPUT,
                (
                    _diagnostic(
                        code="ROUTING_MATRIX_REQUIRED",
                        message="A complete routing matrix is required before solving.",
                    ),
                ),
                elapsed_seconds=perf_counter() - started,
            )

        data = self._build_problem_data(request, request.routing_matrix)
        deadline_diagnostics = self._deadline_precheck(request, request.routing_matrix)
        if deadline_diagnostics:
            return self._failure_result(
                request,
                PlanStatus.INFEASIBLE,
                deadline_diagnostics,
                elapsed_seconds=perf_counter() - started,
            )

        strict_attempt = self._solve_model(
            request,
            request.routing_matrix,
            data,
            allow_dropping=False,
            started_at=started,
        )
        if strict_attempt.assignment is None:
            if strict_attempt.timed_out:
                return self._failure_result(
                    request,
                    PlanStatus.TIMEOUT,
                    (
                        _diagnostic(
                            code="SOLVER_TIMEOUT",
                            message=(
                                "The strict solver reached its time limit before proving "
                                "feasibility or infeasibility."
                            ),
                        ),
                    ),
                    elapsed_seconds=strict_attempt.elapsed_seconds,
                )
            return self._solve_relaxed_diagnostic(request, request.routing_matrix, data, started)

        result = self._extract_solution(
            request,
            request.routing_matrix,
            data,
            strict_attempt.manager,
            strict_attempt.routing,
            strict_attempt.assignment,
            status=PlanStatus.FEASIBLE,
            elapsed_seconds=strict_attempt.elapsed_seconds,
        )
        return self._validate_or_internal_error(request, result)

    def _solve_relaxed_diagnostic(
        self,
        request: PlanningRequest,
        matrix: RoutingMatrix,
        data: _ProblemData,
        started: float,
    ) -> PlanResult:
        relaxed_attempt = self._solve_model(
            request,
            matrix,
            data,
            allow_dropping=True,
            started_at=started,
        )
        if relaxed_attempt.assignment is None:
            status = _routing_failure_status(timed_out=relaxed_attempt.timed_out)
            code = "SOLVER_TIMEOUT" if relaxed_attempt.timed_out else "SOLVER_INFEASIBLE"
            message = (
                "The relaxed diagnostic solver reached its time limit before producing "
                "a partial plan."
                if relaxed_attempt.timed_out
                else "No task subset could be assigned under the hard safety constraints."
            )
            return self._failure_result(
                request,
                status,
                tuple(
                    _task_diagnostic(
                        code,
                        message,
                        task.task_id,
                        task.po_number,
                    )
                    for task in request.tasks
                ),
                elapsed_seconds=relaxed_attempt.elapsed_seconds,
            )

        result = self._extract_solution(
            request,
            matrix,
            data,
            relaxed_attempt.manager,
            relaxed_attempt.routing,
            relaxed_attempt.assignment,
            status=PlanStatus.PARTIALLY_FEASIBLE,
            elapsed_seconds=relaxed_attempt.elapsed_seconds,
        )
        if len(result.scheduled_task_ids) == len(request.tasks):
            result = result.model_copy(update={"status": PlanStatus.FEASIBLE, "diagnostics": ()})
        elif not result.scheduled_task_ids:
            result = result.model_copy(update={"status": PlanStatus.INFEASIBLE})
        return self._validate_or_internal_error(request, result)

    def _validate_or_internal_error(
        self,
        request: PlanningRequest,
        result: PlanResult,
    ) -> PlanResult:
        validation = validate_plan_result(request, result)
        if not validation.valid:
            return self._failure_result(
                request,
                PlanStatus.INTERNAL_ERROR,
                (
                    _diagnostic(
                        code="RESULT_VALIDATION_FAILED",
                        message=(
                            "The solver produced a route plan that failed independent validation."
                        ),
                    ),
                ),
                elapsed_seconds=result.solver_elapsed_seconds,
                warnings=validation.issues,
            )
        return result

    def _static_precheck(self, request: PlanningRequest) -> tuple[TaskDiagnostic, ...]:
        vehicle_by_id = {vehicle.vehicle_id: vehicle for vehicle in request.vehicles}
        active_shifts = tuple(
            shift for shift in request.vehicle_shifts if vehicle_by_id[shift.vehicle_id].enabled
        )
        if not active_shifts:
            return (
                _diagnostic(
                    code="NO_ACTIVE_SHIFTS",
                    message="At least one enabled vehicle shift is required before solving.",
                ),
            )

        diagnostics: list[TaskDiagnostic] = []
        for task in request.tasks:
            compatible_vehicles = tuple(
                vehicle_by_id[shift.vehicle_id]
                for shift in active_shifts
                if task.required_vehicle_tags.issubset(vehicle_by_id[shift.vehicle_id].tags)
            )
            if not compatible_vehicles:
                diagnostics.append(
                    _task_diagnostic(
                        "NO_COMPATIBLE_VEHICLE",
                        "No enabled vehicle shift has the required tags for this task.",
                        task.task_id,
                        task.po_number,
                    )
                )
                continue
            maximum_capacity = max(vehicle.capacity for vehicle in compatible_vehicles)
            if task.quantity > maximum_capacity:
                diagnostics.append(
                    _task_diagnostic(
                        "CAPACITY_EXCEEDED",
                        f"Task quantity {task.quantity} exceeds compatible capacity "
                        f"{maximum_capacity}.",
                        task.task_id,
                        task.po_number,
                    )
                )
        return tuple(diagnostics)

    def _deadline_precheck(
        self,
        request: PlanningRequest,
        matrix: RoutingMatrix,
    ) -> tuple[TaskDiagnostic, ...]:
        diagnostics: list[TaskDiagnostic] = []
        for task in request.tasks:
            timing = self._earliest_individual_timing(request, matrix, task.task_id)
            if timing is None:
                diagnostics.append(
                    _deadline_diagnostic(
                        code="NO_COMPATIBLE_SHIFT_TIME",
                        message=(
                            "No compatible vehicle shift can complete this task and return "
                            "to its configured depot before the shift ends."
                        ),
                        task_id=task.task_id,
                        po_number=task.po_number,
                        due_at=task.due_at,
                        estimated_completion_at=None,
                    )
                )
            elif timing.event_completion_at > task.due_at:
                diagnostics.append(
                    _deadline_diagnostic(
                        code="DEADLINE_IMPOSSIBLE_INDIVIDUALLY",
                        message=(
                            "This PO cannot meet its deadline even when planned by itself "
                            "on the earliest compatible shift."
                        ),
                        task_id=task.task_id,
                        po_number=task.po_number,
                        due_at=task.due_at,
                        estimated_completion_at=timing.event_completion_at,
                    )
                )
        return tuple(diagnostics)

    def _earliest_individual_timing(
        self,
        request: PlanningRequest,
        matrix: RoutingMatrix,
        task_id: str,
    ) -> _TaskTiming | None:
        task = next(task for task in request.tasks if task.task_id == task_id)
        pair = next(pair for pair in expand_tasks((task,), request.plant_location_id))
        vehicle_by_id = {vehicle.vehicle_id: vehicle for vehicle in request.vehicles}
        location_index = _matrix_lookup(matrix)

        def duration(from_location_id: str, to_location_id: str) -> int:
            return matrix.duration_seconds[location_index[from_location_id]][
                location_index[to_location_id]
            ]

        timings: list[_TaskTiming] = []
        for shift in request.vehicle_shifts:
            vehicle = vehicle_by_id[shift.vehicle_id]
            if not vehicle.enabled:
                continue
            if not task.required_vehicle_tags.issubset(vehicle.tags):
                continue
            if task.quantity > vehicle.capacity:
                continue

            pickup_arrival = shift.start + timedelta(
                seconds=duration(shift.start_location_id, pair.pickup.location_id)
            )
            pickup_service_start = max(pickup_arrival, task.ready_at)
            pickup_complete = pickup_service_start + timedelta(seconds=pair.pickup.service_seconds)
            delivery_arrival = pickup_complete + timedelta(
                seconds=duration(pair.pickup.location_id, pair.delivery.location_id)
            )
            delivery_complete = delivery_arrival + timedelta(seconds=pair.delivery.service_seconds)
            route_end = delivery_complete + timedelta(
                seconds=duration(pair.delivery.location_id, shift.end_location_id)
            )
            max_route_end = min(
                shift.end,
                shift.start + timedelta(seconds=_route_duration_limit_seconds(vehicle, shift)),
            )
            if route_end > max_route_end:
                continue
            event_completion = (
                pickup_complete if pair.pickup.completion_due_at else delivery_complete
            )
            timings.append(_TaskTiming(event_completion, route_end))

        if not timings:
            return None
        return min(timings, key=lambda timing: timing.event_completion_at)

    def _build_problem_data(
        self,
        request: PlanningRequest,
        matrix: RoutingMatrix,
    ) -> _ProblemData:
        vehicle_by_id = {vehicle.vehicle_id: vehicle for vehicle in request.vehicles}
        active_shifts = tuple(
            shift for shift in request.vehicle_shifts if vehicle_by_id[shift.vehicle_id].enabled
        )
        vehicles_by_shift = tuple(vehicle_by_id[shift.vehicle_id] for shift in active_shifts)
        pairs = expand_tasks(request.tasks, request.plant_location_id)

        nodes: list[_SolverNode] = []
        pair_node_indices: dict[str, tuple[int, int]] = {}
        compatible_vehicle_indices: dict[str, tuple[int, ...]] = {}
        task_by_id = {task.task_id: task for task in request.tasks}

        for pair in pairs:
            pickup_index = len(nodes)
            nodes.append(self._task_node(pair.pickup))
            delivery_index = len(nodes)
            nodes.append(self._task_node(pair.delivery))
            pair_node_indices[pair.task_id] = (pickup_index, delivery_index)

            task = task_by_id[pair.task_id]
            compatible_vehicle_indices[pair.task_id] = tuple(
                index
                for index, vehicle in enumerate(vehicles_by_shift)
                if task.required_vehicle_tags.issubset(vehicle.tags)
                and _load_units(task.quantity) <= _load_units(vehicle.capacity)
            )

        starts: list[int] = []
        ends: list[int] = []
        for shift in active_shifts:
            starts.append(len(nodes))
            nodes.append(
                _SolverNode(
                    node_id=f"{shift.shift_id}::start",
                    kind=StopKind.DEPOT_START,
                    location_id=shift.start_location_id,
                )
            )
        for shift in active_shifts:
            ends.append(len(nodes))
            nodes.append(
                _SolverNode(
                    node_id=f"{shift.shift_id}::end",
                    kind=StopKind.DEPOT_END,
                    location_id=shift.end_location_id,
                )
            )

        return _ProblemData(
            nodes=tuple(nodes),
            active_shifts=active_shifts,
            vehicles_by_shift=vehicles_by_shift,
            starts=tuple(starts),
            ends=tuple(ends),
            pairs=pairs,
            pair_node_indices=pair_node_indices,
            compatible_vehicle_indices=compatible_vehicle_indices,
            location_index=_matrix_lookup(matrix),
            horizon_start=request.horizon.start,
            max_time_seconds=int((request.horizon.end - request.horizon.start).total_seconds()),
        )

    def _task_node(self, node: ExpandedTaskNode) -> _SolverNode:
        return _SolverNode(
            node_id=node.node_id,
            kind=node.kind,
            location_id=node.location_id,
            load_delta_units=_load_units(node.load_delta),
            load_delta=node.load_delta,
            service_seconds=node.service_seconds,
            task_id=node.task_id,
            ready_at=node.ready_at,
            completion_due_at=node.completion_due_at,
        )

    def _add_objective_and_dimensions(
        self,
        routing: pywrapcp.RoutingModel,
        manager: pywrapcp.RoutingIndexManager,
        matrix: RoutingMatrix,
        data: _ProblemData,
    ) -> None:
        def distance_callback(from_index: int, to_index: int) -> int:
            return _travel_distance(
                data,
                matrix,
                int(manager.IndexToNode(from_index)),
                int(manager.IndexToNode(to_index)),
            )

        def duration_callback(from_index: int, to_index: int) -> int:
            from_node = int(manager.IndexToNode(from_index))
            to_node = int(manager.IndexToNode(to_index))
            return data.nodes[from_node].service_seconds + _travel_duration(
                data,
                matrix,
                from_node,
                to_node,
            )

        def demand_callback(from_index: int) -> int:
            node_number = int(manager.IndexToNode(from_index))
            return data.nodes[node_number].load_delta_units

        def order_callback(_from_index: int, _to_index: int) -> int:
            return 1

        distance_callback_index = routing.RegisterTransitCallback(distance_callback)
        duration_callback_index = routing.RegisterTransitCallback(duration_callback)
        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        order_callback_index = routing.RegisterTransitCallback(order_callback)

        routing.SetArcCostEvaluatorOfAllVehicles(distance_callback_index)
        for vehicle_index in range(len(data.active_shifts)):
            routing.SetFixedCostOfVehicle(self._config.vehicle_fixed_cost, vehicle_index)

        routing.AddDimensionWithVehicleCapacity(
            demand_callback_index,
            0,
            [_load_units(vehicle.capacity) for vehicle in data.vehicles_by_shift],
            True,
            "Capacity",
        )
        routing.AddDimensionWithVehicleCapacity(
            duration_callback_index,
            0,
            [
                _route_duration_limit_seconds(vehicle, shift)
                for vehicle, shift in zip(data.vehicles_by_shift, data.active_shifts, strict=True)
            ],
            True,
            "RouteDuration",
        )
        routing.AddDimension(
            duration_callback_index,
            data.max_time_seconds,
            data.max_time_seconds,
            False,
            "Time",
        )
        time_dimension = routing.GetDimensionOrDie("Time")
        for vehicle_index, (vehicle, shift) in enumerate(
            zip(data.vehicles_by_shift, data.active_shifts, strict=True)
        ):
            shift_start_seconds = _seconds_from_horizon(data, shift.start)
            latest_end = min(
                _seconds_from_horizon(data, shift.end),
                shift_start_seconds + _route_duration_limit_seconds(vehicle, shift),
            )
            time_dimension.CumulVar(routing.Start(vehicle_index)).SetRange(
                shift_start_seconds,
                shift_start_seconds,
            )
            time_dimension.CumulVar(routing.End(vehicle_index)).SetRange(
                shift_start_seconds,
                latest_end,
            )
            routing.AddVariableMinimizedByFinalizer(
                time_dimension.CumulVar(routing.End(vehicle_index))
            )

        for node_number, node in enumerate(data.nodes):
            if node.kind not in {StopKind.PICKUP, StopKind.DELIVERY}:
                continue
            index = manager.NodeToIndex(node_number)
            lower_bound = 0
            upper_bound = data.max_time_seconds
            if node.ready_at is not None:
                lower_bound = max(lower_bound, _seconds_from_horizon(data, node.ready_at))
            if node.completion_due_at is not None:
                latest_service_start = (
                    _seconds_from_horizon(data, node.completion_due_at) - node.service_seconds
                )
                upper_bound = min(upper_bound, latest_service_start)
            time_dimension.CumulVar(index).SetRange(lower_bound, upper_bound)
            routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(index))
        routing.AddDimension(
            order_callback_index,
            0,
            len(data.nodes) + 1,
            True,
            "VisitOrder",
        )

    def _add_pair_and_vehicle_constraints(
        self,
        routing: pywrapcp.RoutingModel,
        manager: pywrapcp.RoutingIndexManager,
        data: _ProblemData,
        *,
        allow_dropping: bool,
    ) -> None:
        order_dimension = routing.GetDimensionOrDie("VisitOrder")
        solver = routing.solver()
        for pair in data.pairs:
            pickup_node, delivery_node = data.pair_node_indices[pair.task_id]
            pickup_index = manager.NodeToIndex(pickup_node)
            delivery_index = manager.NodeToIndex(delivery_node)
            routing.AddPickupAndDelivery(pickup_index, delivery_index)
            solver.Add(routing.VehicleVar(pickup_index) == routing.VehicleVar(delivery_index))
            solver.Add(routing.ActiveVar(pickup_index) == routing.ActiveVar(delivery_index))
            solver.Add(
                order_dimension.CumulVar(pickup_index) <= order_dimension.CumulVar(delivery_index)
            )
            allowed_vehicle_indices = list(data.compatible_vehicle_indices[pair.task_id])
            routing.SetAllowedVehiclesForIndex(allowed_vehicle_indices, pickup_index)
            routing.SetAllowedVehiclesForIndex(allowed_vehicle_indices, delivery_index)
            if allow_dropping:
                routing.AddDisjunction([pickup_index], self._config.dropped_task_penalty)
                routing.AddDisjunction([delivery_index], self._config.dropped_task_penalty)

    def _solve_model(
        self,
        request: PlanningRequest,
        matrix: RoutingMatrix,
        data: _ProblemData,
        *,
        allow_dropping: bool,
        started_at: float,
    ) -> _SolveAttempt:
        manager = pywrapcp.RoutingIndexManager(
            len(data.nodes),
            len(data.active_shifts),
            list(data.starts),
            list(data.ends),
        )
        routing = pywrapcp.RoutingModel(manager)
        self._add_objective_and_dimensions(routing, manager, matrix, data)
        self._add_pair_and_vehicle_constraints(
            routing,
            manager,
            data,
            allow_dropping=allow_dropping,
        )

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        )
        search_parameters.time_limit.FromSeconds(self._config.time_limit_seconds)
        search_parameters.log_search = False

        assignment = routing.SolveWithParameters(search_parameters)
        return _SolveAttempt(
            assignment=assignment,
            manager=manager,
            routing=routing,
            elapsed_seconds=perf_counter() - started_at,
            timed_out=routing.status() == _ROUTING_FAIL_TIMEOUT,
        )

    def _extract_solution(
        self,
        request: PlanningRequest,
        matrix: RoutingMatrix,
        data: _ProblemData,
        manager: pywrapcp.RoutingIndexManager,
        routing: pywrapcp.RoutingModel,
        assignment: pywrapcp.Assignment,
        *,
        status: PlanStatus,
        elapsed_seconds: float,
    ) -> PlanResult:
        routes: list[PlanRoute] = []
        for vehicle_index, shift in enumerate(data.active_shifts):
            route = self._extract_vehicle_route(
                request,
                matrix,
                data,
                manager,
                routing,
                assignment,
                vehicle_index=vehicle_index,
                shift=shift,
            )
            if route is not None:
                routes.append(route)

        scheduled_set = {
            stop.task_id
            for route in routes
            for stop in route.stops
            if stop.kind is StopKind.PICKUP and stop.task_id is not None
        }
        scheduled_task_ids = tuple(
            task.task_id for task in request.tasks if task.task_id in scheduled_set
        )
        unscheduled_task_ids = tuple(
            task.task_id for task in request.tasks if task.task_id not in scheduled_set
        )
        diagnostics = tuple(
            _deadline_diagnostic(
                code="INSUFFICIENT_COMBINED_FLEET_TIME",
                message=(
                    "This PO is feasible by itself, but it was left out of the relaxed "
                    "diagnostic plan because the fleet cannot complete every PO before "
                    "the current deadlines."
                ),
                task_id=task.task_id,
                po_number=task.po_number,
                due_at=task.due_at,
                estimated_completion_at=None,
            )
            for task in request.tasks
            if task.task_id in unscheduled_task_ids
        )
        return PlanResult(
            plan_id=f"{request.scenario_id}:M5",
            status=status,
            routes=tuple(routes),
            diagnostics=diagnostics,
            scheduled_task_ids=scheduled_task_ids,
            unscheduled_task_ids=unscheduled_task_ids,
            total_distance_meters=sum(route.total_distance_meters for route in routes),
            total_driving_seconds=sum(route.driving_seconds for route in routes),
            total_service_seconds=sum(route.service_seconds for route in routes),
            total_waiting_seconds=sum(route.waiting_seconds for route in routes),
            solver_elapsed_seconds=elapsed_seconds,
        )

    def _extract_vehicle_route(
        self,
        request: PlanningRequest,
        matrix: RoutingMatrix,
        data: _ProblemData,
        manager: pywrapcp.RoutingIndexManager,
        routing: pywrapcp.RoutingModel,
        assignment: pywrapcp.Assignment,
        *,
        vehicle_index: int,
        shift: VehicleShift,
    ) -> PlanRoute | None:
        time_dimension = routing.GetDimensionOrDie("Time")
        route_indices: list[int] = []
        index = routing.Start(vehicle_index)
        while not routing.IsEnd(index):
            route_indices.append(index)
            index = assignment.Value(routing.NextVar(index))
        route_indices.append(index)
        task_index_count = sum(
            1
            for route_index in route_indices
            if data.nodes[manager.IndexToNode(route_index)].kind
            in {StopKind.PICKUP, StopKind.DELIVERY}
        )
        if task_index_count == 0:
            return None

        stops: list[PlanStop] = []
        current_time = shift.start
        current_load_units = 0
        total_distance = 0
        driving_seconds = 0
        service_seconds = 0
        waiting_seconds = 0
        peak_load_units = 0

        previous_node_number: int | None = None
        previous_departure_at: datetime | None = None
        for sequence, route_index in enumerate(route_indices):
            node_number = int(manager.IndexToNode(route_index))
            node = data.nodes[node_number]
            distance = 0
            duration = 0
            service_start_seconds = assignment.Value(time_dimension.CumulVar(route_index))
            service_start_at = data.horizon_start + timedelta(seconds=service_start_seconds)
            if previous_node_number is not None:
                distance = _travel_distance(data, matrix, previous_node_number, node_number)
                duration = _travel_duration(data, matrix, previous_node_number, node_number)
                if previous_departure_at is not None:
                    current_time = previous_departure_at + timedelta(seconds=duration)
                total_distance += distance
                driving_seconds += duration

            arrival_at = current_time
            waiting_seconds += int((service_start_at - arrival_at).total_seconds())
            departure_at = service_start_at + timedelta(seconds=node.service_seconds)
            current_time = departure_at
            previous_departure_at = departure_at
            current_load_units += node.load_delta_units
            peak_load_units = max(peak_load_units, current_load_units)
            service_seconds += node.service_seconds
            due_at = node.completion_due_at
            slack_seconds = (
                int((due_at - departure_at).total_seconds()) if due_at is not None else None
            )
            stops.append(
                PlanStop(
                    sequence=sequence,
                    node_id=node.node_id,
                    kind=node.kind,
                    location_id=node.location_id,
                    task_id=node.task_id,
                    arrival_at=arrival_at,
                    service_start_at=service_start_at,
                    departure_at=departure_at,
                    load_after=_load_decimal(current_load_units),
                    distance_from_previous_meters=distance,
                    duration_from_previous_seconds=duration,
                    due_at=due_at,
                    slack_seconds=slack_seconds,
                )
            )
            previous_node_number = node_number

        return PlanRoute(
            vehicle_id=shift.vehicle_id,
            shift_id=shift.shift_id,
            stops=tuple(stops),
            total_distance_meters=total_distance,
            driving_seconds=driving_seconds,
            service_seconds=service_seconds,
            waiting_seconds=waiting_seconds,
            peak_load=_load_decimal(peak_load_units),
        )

    def _failure_result(
        self,
        request: PlanningRequest,
        status: PlanStatus,
        diagnostics: Sequence[TaskDiagnostic],
        *,
        elapsed_seconds: float,
        warnings: Sequence[str] = (),
    ) -> PlanResult:
        scheduled_task_ids: tuple[str, ...] = ()
        unscheduled_task_ids = tuple(task.task_id for task in request.tasks)
        return PlanResult(
            plan_id=f"{request.scenario_id}:M5",
            status=status,
            routes=(),
            diagnostics=tuple(diagnostics),
            scheduled_task_ids=scheduled_task_ids,
            unscheduled_task_ids=unscheduled_task_ids,
            solver_elapsed_seconds=elapsed_seconds,
            warnings=tuple(warnings),
        )
