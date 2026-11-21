"""Figures that make plans comparable (plan §10.8): trucks used, route lengths, use."""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain.models import PlanningRequest, Vehicle, VehicleShift
from backend.app.domain.results import PlanMetrics, PlanRoute


def route_time_allowance_seconds(vehicle: Vehicle, shift: VehicleShift) -> int:
    """The longest a route may last: the shift, capped by the truck's and shift's limits."""
    limits = [int((shift.end - shift.start).total_seconds())]
    if vehicle.maximum_route_duration_seconds is not None:
        limits.append(vehicle.maximum_route_duration_seconds)
    if shift.maximum_route_duration_seconds is not None:
        limits.append(shift.maximum_route_duration_seconds)
    return min(limits)


def route_duration_seconds(route: PlanRoute, shift: VehicleShift) -> int:
    """Shift start to arrival at the end depot, waiting included."""
    if route.total_duration_seconds is not None:
        return route.total_duration_seconds
    if not route.stops:
        return 0
    return int((route.stops[-1].arrival_at - shift.start).total_seconds())


def plan_metrics(
    request: PlanningRequest,
    routes: Sequence[PlanRoute],
    *,
    objective_value: int | None = None,
) -> PlanMetrics:
    vehicles = {vehicle.vehicle_id: vehicle for vehicle in request.vehicles}
    shifts = {shift.shift_id: shift for shift in request.vehicle_shifts}
    available = sum(
        1
        for shift in request.vehicle_shifts
        if shift.vehicle_id in vehicles and vehicles[shift.vehicle_id].enabled
    )
    durations: list[int] = []
    load_shares: list[float] = []
    time_shares: list[float] = []
    for route in routes:
        shift = shifts.get(route.shift_id)
        vehicle = vehicles.get(route.vehicle_id)
        if shift is None or vehicle is None:
            continue
        duration = route_duration_seconds(route, shift)
        durations.append(duration)
        load_shares.append(float(route.peak_load / vehicle.capacity))
        allowance = route_time_allowance_seconds(vehicle, shift)
        time_shares.append(duration / allowance if allowance else 0.0)
    return PlanMetrics(
        truck_shifts_used=len(routes),
        truck_shifts_available=available,
        longest_route_seconds=max(durations, default=0),
        shortest_route_seconds=min(durations, default=0),
        longest_working_seconds=max(
            (route.driving_seconds + route.service_seconds for route in routes), default=0
        ),
        load_utilisation=round(sum(load_shares) / len(load_shares), 3) if load_shares else 0,
        time_utilisation=round(sum(time_shares) / len(time_shares), 3) if time_shares else 0,
        objective_value=objective_value,
    )
