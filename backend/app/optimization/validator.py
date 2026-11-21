"""Independent structural validation for optimized route results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from backend.app.domain.enums import PlanStatus, StopKind
from backend.app.domain.models import PlanningRequest, Vehicle, VehicleShift
from backend.app.domain.results import PlanResult, PlanRoute, PlanStop
from backend.app.optimization.task_expander import ExpandedTaskNode, expand_tasks


@dataclass(frozen=True, slots=True)
class PlanValidationResult:
    """Outcome from recalculating and checking a returned route plan."""

    valid: bool
    issues: tuple[str, ...] = ()


def _seconds_between(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds())


def _matrix_value(
    request: PlanningRequest,
    from_location_id: str,
    to_location_id: str,
    *,
    matrix_name: str,
) -> int:
    if request.routing_matrix is None:
        raise ValueError("routing matrix is required to validate plan totals")
    location_index = {
        location_id: index for index, location_id in enumerate(request.routing_matrix.location_ids)
    }
    from_index = location_index[from_location_id]
    to_index = location_index[to_location_id]
    matrix = (
        request.routing_matrix.distance_meters
        if matrix_name == "distance"
        else request.routing_matrix.duration_seconds
    )
    return matrix[from_index][to_index]


def _route_time_allowance_seconds(vehicle: Vehicle, shift: VehicleShift) -> int:
    """The longest a route may last: the shift, capped by the truck's and shift's limits."""
    limits = [_seconds_between(shift.start, shift.end)]
    if vehicle.maximum_route_duration_seconds is not None:
        limits.append(vehicle.maximum_route_duration_seconds)
    if shift.maximum_route_duration_seconds is not None:
        limits.append(shift.maximum_route_duration_seconds)
    return min(limits)


def _task_nodes_by_id(request: PlanningRequest) -> dict[str, ExpandedTaskNode]:
    nodes: dict[str, ExpandedTaskNode] = {}
    for task in expand_tasks(request.tasks, request.plant_location_id):
        nodes[task.pickup.node_id] = task.pickup
        nodes[task.delivery.node_id] = task.delivery
    return nodes


def _expected_service_start(stop: PlanStop, node: ExpandedTaskNode | None) -> datetime:
    if node is None or node.ready_at is None:
        return stop.arrival_at
    return max(stop.arrival_at, node.ready_at)


def _validate_route(
    request: PlanningRequest,
    route: PlanRoute,
    *,
    task_nodes: dict[str, ExpandedTaskNode],
) -> tuple[list[str], dict[str, list[tuple[str, StopKind, int]]]]:
    issues: list[str] = []
    task_positions: dict[str, list[tuple[str, StopKind, int]]] = {}

    vehicle_by_id = {vehicle.vehicle_id: vehicle for vehicle in request.vehicles}
    shift_by_id = {shift.shift_id: shift for shift in request.vehicle_shifts}
    vehicle = vehicle_by_id.get(route.vehicle_id)
    shift = shift_by_id.get(route.shift_id)
    route_key = f"{route.vehicle_id}/{route.shift_id}"
    if vehicle is None:
        return ([f"route {route_key} references unknown vehicle"], task_positions)
    if shift is None:
        return ([f"route {route_key} references unknown shift"], task_positions)
    if shift.vehicle_id != route.vehicle_id:
        issues.append(f"route {route_key} shift belongs to vehicle {shift.vehicle_id}")
    if not vehicle.enabled:
        issues.append(f"route {route_key} uses a disabled vehicle")
    tasks_by_id = {task.task_id: task for task in request.tasks}

    stops = route.stops
    if len(stops) < 2:
        issues.append(f"route {route_key} must include start and end depot stops")
        return (issues, task_positions)
    if stops[0].kind is not StopKind.DEPOT_START:
        issues.append(f"route {route_key} first stop is not a depot start")
    if stops[-1].kind is not StopKind.DEPOT_END:
        issues.append(f"route {route_key} last stop is not a depot end")
    if stops[0].location_id != shift.start_location_id:
        issues.append(f"route {route_key} starts at {stops[0].location_id}, not shift start")
    if stops[-1].location_id != shift.end_location_id:
        issues.append(f"route {route_key} ends at {stops[-1].location_id}, not shift end")
    if stops[0].arrival_at != shift.start or stops[0].departure_at != shift.start:
        issues.append(f"route {route_key} start depot time does not match shift start")
    if stops[-1].departure_at > shift.end:
        issues.append(f"route {route_key} ends after the shift end")

    expected_load = Decimal(0)
    peak_load = Decimal(0)
    total_distance = 0
    driving_seconds = 0
    service_seconds = 0
    waiting_seconds = 0

    for expected_sequence, stop in enumerate(stops):
        if stop.sequence != expected_sequence:
            issues.append(f"route {route_key} stop sequence is not consecutive")
        if expected_sequence == 0:
            if stop.distance_from_previous_meters != 0:
                issues.append(f"route {route_key} start stop reports prior distance")
            if stop.duration_from_previous_seconds != 0:
                issues.append(f"route {route_key} start stop reports prior duration")
        else:
            previous = stops[expected_sequence - 1]
            expected_distance = _matrix_value(
                request,
                previous.location_id,
                stop.location_id,
                matrix_name="distance",
            )
            expected_duration = _matrix_value(
                request,
                previous.location_id,
                stop.location_id,
                matrix_name="duration",
            )
            total_distance += expected_distance
            driving_seconds += expected_duration
            if stop.distance_from_previous_meters != expected_distance:
                issues.append(f"route {route_key} stop {stop.sequence} distance is inconsistent")
            if stop.duration_from_previous_seconds != expected_duration:
                issues.append(f"route {route_key} stop {stop.sequence} duration is inconsistent")
            if _seconds_between(previous.departure_at, stop.arrival_at) != expected_duration:
                issues.append(
                    f"route {route_key} stop {stop.sequence} arrival time is inconsistent"
                )

        node = task_nodes.get(stop.node_id)
        if stop.kind in {StopKind.PICKUP, StopKind.DELIVERY}:
            if node is None:
                issues.append(
                    f"route {route_key} stop {stop.sequence} references unknown task node"
                )
            else:
                if stop.task_id != node.task_id:
                    issues.append(f"route {route_key} stop {stop.sequence} task ID is inconsistent")
                if stop.kind is not node.kind:
                    issues.append(f"route {route_key} stop {stop.sequence} kind is inconsistent")
                task = tasks_by_id.get(node.task_id)
                if (
                    task is not None
                    and stop.kind is StopKind.PICKUP
                    and not task.required_vehicle_tags.issubset(vehicle.tags)
                ):
                    issues.append(
                        f"route {route_key} carries task {task.task_id} without its required "
                        "vehicle tags"
                    )
                if stop.location_id != node.location_id:
                    issues.append(
                        f"route {route_key} stop {stop.sequence} location is inconsistent"
                    )
                expected_service_start = _expected_service_start(stop, node)
                if stop.service_start_at != expected_service_start:
                    issues.append(
                        f"route {route_key} stop {stop.sequence} service start is inconsistent"
                    )
                if (
                    _seconds_between(stop.service_start_at, stop.departure_at)
                    != node.service_seconds
                ):
                    issues.append(
                        f"route {route_key} stop {stop.sequence} service duration is inconsistent"
                    )
                expected_load += node.load_delta
                service_seconds += node.service_seconds
                task_positions.setdefault(node.task_id, []).append(
                    (route_key, stop.kind, stop.sequence)
                )
                if node.completion_due_at is not None:
                    if stop.due_at != node.completion_due_at:
                        issues.append(f"route {route_key} stop {stop.sequence} due time is missing")
                    expected_slack = _seconds_between(stop.departure_at, node.completion_due_at)
                    if stop.slack_seconds != expected_slack:
                        issues.append(
                            f"route {route_key} stop {stop.sequence} slack is inconsistent"
                        )
                    if expected_slack < 0:
                        issues.append(
                            f"route {route_key} stop {stop.sequence} misses its hard deadline"
                        )
        elif stop.kind in {StopKind.DEPOT_START, StopKind.DEPOT_END}:
            if node is not None:
                issues.append(f"route {route_key} depot stop uses a task node ID")
        else:
            issues.append(f"route {route_key} stop {stop.sequence} has unsupported kind")

        waiting_seconds += _seconds_between(stop.arrival_at, stop.service_start_at)
        if stop.load_after != expected_load:
            issues.append(f"route {route_key} stop {stop.sequence} load is inconsistent")
        if expected_load < 0:
            issues.append(f"route {route_key} stop {stop.sequence} load drops below zero")
        if expected_load > vehicle.capacity:
            issues.append(f"route {route_key} stop {stop.sequence} exceeds vehicle capacity")
        peak_load = max(peak_load, expected_load)

    if expected_load != 0:
        issues.append(f"route {route_key} does not return to zero load")
    if route.total_distance_meters != total_distance:
        issues.append(f"route {route_key} total distance is inconsistent")
    if route.driving_seconds != driving_seconds:
        issues.append(f"route {route_key} driving seconds are inconsistent")
    if route.service_seconds != service_seconds:
        issues.append(f"route {route_key} service seconds are inconsistent")
    if route.waiting_seconds != waiting_seconds:
        issues.append(f"route {route_key} waiting seconds are inconsistent")
    if route.peak_load != peak_load:
        issues.append(f"route {route_key} peak load is inconsistent")
    allowance = _route_time_allowance_seconds(vehicle, shift)
    if _seconds_between(shift.start, stops[-1].arrival_at) > allowance:
        issues.append(f"route {route_key} lasts longer than its maximum route duration")
    distance_limit = vehicle.maximum_route_distance_meters
    if distance_limit is not None and total_distance > distance_limit:
        issues.append(f"route {route_key} exceeds the vehicle's maximum route distance")

    return issues, task_positions


def validate_plan_result(request: PlanningRequest, result: PlanResult) -> PlanValidationResult:
    """Recalculate strict or partial plans and reject unsafe route output."""
    if result.status not in {PlanStatus.FEASIBLE, PlanStatus.PARTIALLY_FEASIBLE}:
        return PlanValidationResult(valid=True)
    if request.routing_matrix is None:
        return PlanValidationResult(valid=False, issues=("routing matrix is required",))

    issues: list[str] = []
    task_nodes = _task_nodes_by_id(request)
    all_positions: dict[str, list[tuple[str, StopKind, int]]] = {}

    for route in result.routes:
        route_issues, route_positions = _validate_route(
            request,
            route,
            task_nodes=task_nodes,
        )
        issues.extend(route_issues)
        for task_id, positions in route_positions.items():
            all_positions.setdefault(task_id, []).extend(positions)

    request_task_ids = tuple(task.task_id for task in request.tasks)
    request_task_id_set = set(request_task_ids)
    scheduled_task_ids = tuple(result.scheduled_task_ids)
    unscheduled_task_ids = tuple(result.unscheduled_task_ids)
    if len(scheduled_task_ids) != len(set(scheduled_task_ids)):
        issues.append("scheduled_task_ids contains duplicates")
    if len(unscheduled_task_ids) != len(set(unscheduled_task_ids)):
        issues.append("unscheduled_task_ids contains duplicates")
    if set(scheduled_task_ids) - request_task_id_set:
        issues.append("scheduled_task_ids references unknown tasks")
    if set(unscheduled_task_ids) - request_task_id_set:
        issues.append("unscheduled_task_ids references unknown tasks")
    if set(scheduled_task_ids) & set(unscheduled_task_ids):
        issues.append("scheduled and unscheduled task IDs overlap")
    if result.status is PlanStatus.FEASIBLE and scheduled_task_ids != request_task_ids:
        issues.append("scheduled_task_ids must match request task order for a feasible plan")
    if result.status is PlanStatus.FEASIBLE and result.unscheduled_task_ids:
        issues.append("feasible plan must not contain unscheduled tasks")
    if result.status is PlanStatus.PARTIALLY_FEASIBLE:
        expected_partition = set(scheduled_task_ids) | set(unscheduled_task_ids)
        if expected_partition != request_task_id_set:
            issues.append("partial plan must partition every request task")
        if not scheduled_task_ids:
            issues.append("partial plan must contain at least one scheduled task")
        if not unscheduled_task_ids:
            issues.append("partial plan must contain at least one unscheduled task")

    for task_id in scheduled_task_ids:
        positions = all_positions.get(task_id, [])
        if len(positions) != 2:
            issues.append(f"task {task_id} must appear exactly once as pickup and delivery")
            continue
        route_keys = {position[0] for position in positions}
        kinds = {position[1] for position in positions}
        if route_keys and len(route_keys) != 1:
            issues.append(f"task {task_id} pickup and delivery are on different routes")
        if kinds != {StopKind.PICKUP, StopKind.DELIVERY}:
            issues.append(f"task {task_id} must have one pickup and one delivery")
        pickup_sequence = next(
            position[2] for position in positions if position[1] is StopKind.PICKUP
        )
        delivery_sequence = next(
            position[2] for position in positions if position[1] is StopKind.DELIVERY
        )
        if pickup_sequence >= delivery_sequence:
            issues.append(f"task {task_id} delivery occurs before pickup")

    for task_id in set(all_positions) - set(scheduled_task_ids):
        if task_id not in set(unscheduled_task_ids):
            issues.append(f"route contains task {task_id} outside scheduled_task_ids")

    for task_id in unscheduled_task_ids:
        if all_positions.get(task_id):
            issues.append(f"unscheduled task {task_id} appears in a route")

    total_distance = sum(route.total_distance_meters for route in result.routes)
    total_driving = sum(route.driving_seconds for route in result.routes)
    total_service = sum(route.service_seconds for route in result.routes)
    total_waiting = sum(route.waiting_seconds for route in result.routes)
    if result.total_distance_meters != total_distance:
        issues.append("plan total distance is inconsistent")
    if result.total_driving_seconds != total_driving:
        issues.append("plan total driving seconds are inconsistent")
    if result.total_service_seconds != total_service:
        issues.append("plan total service seconds are inconsistent")
    if result.total_waiting_seconds != total_waiting:
        issues.append("plan total waiting seconds are inconsistent")

    return PlanValidationResult(valid=not issues, issues=tuple(issues))
