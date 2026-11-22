"""OR-Tools based capacity, time-window, and pickup-delivery route solver."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Final

from ortools.constraint_solver import pywrapcp

from backend.app.domain.enums import PlanStatus, StopKind
from backend.app.domain.models import (
    PlanningRequest,
    RoutingMatrix,
    Vehicle,
    VehicleShift,
)
from backend.app.domain.options import priority_weight
from backend.app.domain.results import PlanResult, PlanRoute, PlanStop, TaskDiagnostic
from backend.app.optimization.metrics import plan_metrics
from backend.app.optimization.objective import SolveSettings, search_parameters
from backend.app.optimization.task_expander import ExpandedTask, ExpandedTaskNode, expand_tasks
from backend.app.optimization.validator import validate_plan_result

_LOAD_SCALE: Final = Decimal("1000")
_ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED: Final = 2
_ROUTING_FAIL: Final = 3
_ROUTING_FAIL_TIMEOUT: Final = 4
_TIME_LIMIT_SHARE: Final = 0.95
"""A search that found nothing after this share of its time limit ran out of time."""
TIME_LIMIT_REACHED_CODE: Final = "SOLVER_TIME_LIMIT_REACHED"
TIME_LIMIT_REACHED_MESSAGE: Final = (
    "The search stopped at its time limit while it was still fitting POs in, so a longer "
    "time limit may plan more of them."
)
_NO_DISTANCE_LIMIT: Final = 2**40
"""Route-distance capacity for trucks without a limit: about a billion kilometres."""


@dataclass(frozen=True, slots=True)
class SolverConfig:
    """Deterministic solver controls for the backend route optimizer."""

    time_limit_seconds: int = 10
    vehicle_fixed_cost: int = 1_000_000
    dropped_task_penalty: int = 100_000_000
    """Cost of leaving out one Routine task's pickup or delivery; higher priorities
    multiply it by their weight (1, 2, 4, 8, 16)."""
    transit_matrix_max_nodes: int = 1_000
    """Up to this many routing nodes, travel and load figures are handed to OR-Tools as
    precomputed matrices, so a thorough search spends its time searching. Larger models
    use Python callbacks, which give the same values with less memory."""

    def __post_init__(self) -> None:
        if self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be positive")
        if self.transit_matrix_max_nodes < 0:
            raise ValueError("transit_matrix_max_nodes must be non-negative")
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
    task_weights: dict[str, int]
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
    objective_value: int | None = None
    cut_short: bool = False
    """A plan was found, but the time limit stopped the search before it settled."""


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


def _route_distance_limit_meters(vehicle: Vehicle) -> int:
    limit = vehicle.maximum_route_distance_meters
    return _NO_DISTANCE_LIMIT if limit is None else limit


def _matrix_lookup(matrix: RoutingMatrix) -> dict[str, int]:
    return {location_id: index for index, location_id in enumerate(matrix.location_ids)}


def _seconds_from_horizon(data: _ProblemData, value: datetime) -> int:
    return int((value.astimezone(UTC) - data.horizon_start).total_seconds())


def _with_priorities(
    request: PlanningRequest, diagnostics: Sequence[TaskDiagnostic]
) -> tuple[TaskDiagnostic, ...]:
    """Each task diagnostic shows the task's priority (plan §10.4)."""
    priorities = {task.task_id: task.priority for task in request.tasks}
    return tuple(
        diagnostic.model_copy(update={"priority": priorities[diagnostic.task_id]})
        if diagnostic.task_id in priorities and diagnostic.priority is None
        else diagnostic
        for diagnostic in diagnostics
    )


def _routing_failure_status(*, timed_out: bool) -> PlanStatus:
    return PlanStatus.TIMEOUT if timed_out else PlanStatus.INFEASIBLE


def _ran_out_of_time(
    status: int, *, found: bool, searched_seconds: float, time_limit_seconds: int
) -> bool:
    """Whether a search that found no plan stopped because of its time limit.

    OR-Tools reports ``ROUTING_FAIL_TIMEOUT`` when the limit stops the search. When the
    limit is reached while it is still building a first solution, it can report a plain
    ``ROUTING_FAIL`` instead: measured in V1.1-M7 on a 1,000-task scenario, status 3
    after the full 30 s. A search that found nothing after using nearly all of its time
    is therefore treated as out of time, not as proof that the POs cannot all fit.
    """
    if status == _ROUTING_FAIL_TIMEOUT:
        return True
    return (
        not found
        and status == _ROUTING_FAIL
        and searched_seconds >= _TIME_LIMIT_SHARE * time_limit_seconds
    )


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

    @property
    def config(self) -> SolverConfig:
        return self._config

    def default_settings(self) -> SolveSettings:
        """Version 1.0's objective and search, with this solver's time limit."""
        return SolveSettings(
            time_limit_seconds=self._config.time_limit_seconds,
            vehicle_fixed_cost=self._config.vehicle_fixed_cost,
        )

    def solve(self, request: PlanningRequest, settings: SolveSettings | None = None) -> PlanResult:
        """Return a validated route plan or a controlled infeasibility/diagnostic result.

        ``settings`` choose the objective and the search; without them the solve is
        exactly Version 1.0's.
        """
        settings = settings or self.default_settings()
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
            settings=settings,
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
            return self._solve_relaxed_diagnostic(
                request, request.routing_matrix, data, started, settings
            )

        result = self._extract_solution(
            request,
            request.routing_matrix,
            data,
            strict_attempt.manager,
            strict_attempt.routing,
            strict_attempt.assignment,
            status=PlanStatus.FEASIBLE,
            elapsed_seconds=strict_attempt.elapsed_seconds,
            objective_value=strict_attempt.objective_value,
        )
        return self._validate_or_internal_error(request, result)

    def _solve_relaxed_diagnostic(
        self,
        request: PlanningRequest,
        matrix: RoutingMatrix,
        data: _ProblemData,
        started: float,
        settings: SolveSettings,
    ) -> PlanResult:
        relaxed_attempt = self._solve_model(
            request,
            matrix,
            data,
            allow_dropping=True,
            started_at=started,
            settings=settings,
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
            objective_value=relaxed_attempt.objective_value,
        )
        if len(result.scheduled_task_ids) == len(request.tasks):
            result = result.model_copy(update={"status": PlanStatus.FEASIBLE, "diagnostics": ()})
        else:
            if not result.scheduled_task_ids:
                result = result.model_copy(update={"status": PlanStatus.INFEASIBLE})
            if relaxed_attempt.cut_short:
                # The POs left out may fit after all: say so for the whole plan.
                note = _diagnostic(code=TIME_LIMIT_REACHED_CODE, message=TIME_LIMIT_REACHED_MESSAGE)
                result = result.model_copy(update={"diagnostics": (note, *result.diagnostics)})
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
            if timing is None and self._only_distance_blocks(request, matrix, task.task_id):
                diagnostics.append(
                    _deadline_diagnostic(
                        code="ROUTE_DISTANCE_LIMIT_EXCEEDED",
                        message=(
                            "Every truck that could carry this PO in time would exceed its "
                            "maximum route distance, even with this PO alone. Raise a "
                            "truck's distance limit or add a truck without one."
                        ),
                        task_id=task.task_id,
                        po_number=task.po_number,
                        due_at=task.due_at,
                        estimated_completion_at=None,
                    )
                )
            elif timing is None:
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

    def _only_distance_blocks(
        self,
        request: PlanningRequest,
        matrix: RoutingMatrix,
        task_id: str,
    ) -> bool:
        """Whether a truck could serve the task alone in time but for its distance limit."""
        timing = self._earliest_individual_timing(request, matrix, task_id, honour_distance=False)
        task = next(task for task in request.tasks if task.task_id == task_id)
        return timing is not None and timing.event_completion_at <= task.due_at

    def _earliest_individual_timing(
        self,
        request: PlanningRequest,
        matrix: RoutingMatrix,
        task_id: str,
        *,
        honour_distance: bool = True,
    ) -> _TaskTiming | None:
        task = next(task for task in request.tasks if task.task_id == task_id)
        pair = next(pair for pair in expand_tasks((task,), request.plant_location_id))
        vehicle_by_id = {vehicle.vehicle_id: vehicle for vehicle in request.vehicles}
        location_index = _matrix_lookup(matrix)

        def duration(from_location_id: str, to_location_id: str) -> int:
            return matrix.duration_seconds[location_index[from_location_id]][
                location_index[to_location_id]
            ]

        def distance(from_location_id: str, to_location_id: str) -> int:
            return matrix.distance_meters[location_index[from_location_id]][
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
            if honour_distance and vehicle.maximum_route_distance_meters is not None:
                route_distance = (
                    distance(shift.start_location_id, pair.pickup.location_id)
                    + distance(pair.pickup.location_id, pair.delivery.location_id)
                    + distance(pair.delivery.location_id, shift.end_location_id)
                )
                if route_distance > vehicle.maximum_route_distance_meters:
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
            task_weights={task.task_id: priority_weight(task.priority) for task in request.tasks},
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
        settings: SolveSettings,
    ) -> None:
        (
            distance_callback_index,
            duration_callback_index,
            demand_callback_index,
            order_callback_index,
        ) = self._register_transits(routing, manager, matrix, data)

        routing.SetArcCostEvaluatorOfAllVehicles(distance_callback_index)
        if settings.vehicle_fixed_cost:
            for vehicle_index in range(len(data.active_shifts)):
                routing.SetFixedCostOfVehicle(settings.vehicle_fixed_cost, vehicle_index)

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
        if settings.span_cost_coefficient:
            # BALANCE_WORKLOAD (plan §10.2): a cost on the longest route's working time.
            routing.GetDimensionOrDie("RouteDuration").SetGlobalSpanCostCoefficient(
                settings.span_cost_coefficient
            )
        self._add_limits_and_time_windows(
            routing,
            manager,
            data,
            distance_callback_index=distance_callback_index,
            duration_callback_index=duration_callback_index,
            order_callback_index=order_callback_index,
        )

    def _register_transits(
        self,
        routing: pywrapcp.RoutingModel,
        manager: pywrapcp.RoutingIndexManager,
        matrix: RoutingMatrix,
        data: _ProblemData,
    ) -> tuple[int, int, int, int]:
        """Distance, duration (service plus travel), load change, and visit order.

        Precomputed node matrices (plan §10.3) and Python callbacks return the same
        values; matrices only make each lookup cheaper.
        """
        node_count = len(data.nodes)
        if node_count <= self._config.transit_matrix_max_nodes:
            positions = [data.location_index[node.location_id] for node in data.nodes]
            distances = [
                [matrix.distance_meters[origin][destination] for destination in positions]
                for origin in positions
            ]
            durations = [
                [
                    data.nodes[from_node].service_seconds
                    + matrix.duration_seconds[origin][destination]
                    for destination in positions
                ]
                for from_node, origin in enumerate(positions)
            ]
            return (
                routing.RegisterTransitMatrix(distances),
                routing.RegisterTransitMatrix(durations),
                routing.RegisterUnaryTransitVector([node.load_delta_units for node in data.nodes]),
                routing.RegisterUnaryTransitVector([1] * node_count),
            )

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

        return (
            routing.RegisterTransitCallback(distance_callback),
            routing.RegisterTransitCallback(duration_callback),
            routing.RegisterUnaryTransitCallback(demand_callback),
            routing.RegisterTransitCallback(order_callback),
        )

    def _add_limits_and_time_windows(
        self,
        routing: pywrapcp.RoutingModel,
        manager: pywrapcp.RoutingIndexManager,
        data: _ProblemData,
        *,
        distance_callback_index: int,
        duration_callback_index: int,
        order_callback_index: int,
    ) -> None:
        if any(
            vehicle.maximum_route_distance_meters is not None for vehicle in data.vehicles_by_shift
        ):
            # Plan §10.5. Added only when a truck has a limit, so scenarios without one
            # are solved exactly as in Version 1.0.
            routing.AddDimensionWithVehicleCapacity(
                distance_callback_index,
                0,
                [_route_distance_limit_meters(vehicle) for vehicle in data.vehicles_by_shift],
                True,
                "RouteDistance",
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
                # Priority (plan §10.4): leaving out a task costs its weight, so the
                # partial plan drops the set of tasks with the least total weight.
                penalty = self._config.dropped_task_penalty * data.task_weights[pair.task_id]
                routing.AddDisjunction([pickup_index], penalty)
                routing.AddDisjunction([delivery_index], penalty)

    def _solve_model(
        self,
        request: PlanningRequest,
        matrix: RoutingMatrix,
        data: _ProblemData,
        *,
        allow_dropping: bool,
        started_at: float,
        settings: SolveSettings,
    ) -> _SolveAttempt:
        manager = pywrapcp.RoutingIndexManager(
            len(data.nodes),
            len(data.active_shifts),
            list(data.starts),
            list(data.ends),
        )
        routing = pywrapcp.RoutingModel(manager)
        self._add_objective_and_dimensions(routing, manager, matrix, data, settings)
        self._add_pair_and_vehicle_constraints(
            routing,
            manager,
            data,
            allow_dropping=allow_dropping,
        )

        search_started = perf_counter()
        assignment = routing.SolveWithParameters(search_parameters(settings))
        searched_seconds = perf_counter() - search_started
        status = routing.status()
        return _SolveAttempt(
            assignment=assignment,
            manager=manager,
            routing=routing,
            elapsed_seconds=perf_counter() - started_at,
            timed_out=_ran_out_of_time(
                status,
                found=assignment is not None,
                searched_seconds=searched_seconds,
                time_limit_seconds=settings.time_limit_seconds,
            ),
            objective_value=int(assignment.ObjectiveValue()) if assignment is not None else None,
            cut_short=(
                assignment is not None
                and status == _ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED
            ),
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
        objective_value: int | None = None,
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
                    "This PO can be planned by itself, but there is not enough fleet time, "
                    "capacity, or route allowance to plan it with the others. When not "
                    "everything fits, lower-priority POs are left out first."
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
            diagnostics=_with_priorities(request, diagnostics),
            scheduled_task_ids=scheduled_task_ids,
            unscheduled_task_ids=unscheduled_task_ids,
            total_distance_meters=sum(route.total_distance_meters for route in routes),
            total_driving_seconds=sum(route.driving_seconds for route in routes),
            total_service_seconds=sum(route.service_seconds for route in routes),
            total_waiting_seconds=sum(route.waiting_seconds for route in routes),
            solver_elapsed_seconds=elapsed_seconds,
            metrics=plan_metrics(request, routes, objective_value=objective_value),
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
            total_duration_seconds=int((stops[-1].arrival_at - shift.start).total_seconds()),
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
            diagnostics=_with_priorities(request, diagnostics),
            scheduled_task_ids=scheduled_task_ids,
            unscheduled_task_ids=unscheduled_task_ids,
            solver_elapsed_seconds=elapsed_seconds,
            warnings=tuple(warnings),
            metrics=plan_metrics(request, ()),
        )
