"""A plan in planner language: plain status, names, local times, and units (plan §11.1).

Pure functions over the backend's plan JSON and the scenario, shared by the Results
page, the exports, and the run sheets, so the screen and the files always agree. Stops
show location **names** and PO numbers instead of internal IDs, times are plant-local,
distances are kilometres, and durations are ``h:mm``.

Google Maps links follow decision D1: Google-derived locations are shown through
Google, never on another map. A link carries at most nine waypoints and 2,048
characters (Google Maps URLs), so longer routes are split into consecutive links.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

from frontend.state.optimization import BALANCE_STRENGTHS, OBJECTIVES, SEARCH_EFFORTS
from frontend.state.scenario_state import rows
from frontend.state.settings import DEFAULT_TIMEZONE, planner_defaults
from frontend.state.tasks import PRIORITY_LABELS
from frontend.state.timeutil import to_local
from frontend.state.units import format_km, seconds_to_hmm

JsonObject = dict[str, Any]

STATUS_TEXT: Mapping[str, tuple[str, str]] = {
    "FEASIBLE": ("success", "Every PO is planned and meets its due time."),
    "PARTIALLY_FEASIBLE": (
        "warning",
        "Some POs could not be planned; they are listed below with the reason. Every "
        "planned PO meets its due time.",
    ),
    "INFEASIBLE": ("error", "No PO could be planned. The reasons are listed below."),
    "INVALID_INPUT": (
        "error",
        "Planning could not start because of the inputs. The problems are listed below.",
    ),
    "TIMEOUT": (
        "warning",
        "The search ran out of time before it found a plan. Raise the time limit on the "
        "Optimize page, or split a large scenario (for example one per day), and solve "
        "again.",
    ),
    "INTERNAL_ERROR": (
        "error",
        "The plan failed the app's own safety check, so it is not shown. Solve again; if "
        "it happens again, report the plan ID.",
    ),
}
"""Plan status → (level, one sentence a planner can act on)."""

STATUS_SHORT: Mapping[str, str] = {
    "FEASIBLE": "All POs planned",
    "PARTIALLY_FEASIBLE": "Partly planned",
    "INFEASIBLE": "Nothing planned",
    "INVALID_INPUT": "Inputs need fixing",
    "TIMEOUT": "Ran out of time",
    "INTERNAL_ERROR": "Failed safety check",
}

ACTION_LABELS: Mapping[str, str] = {
    "DEPOT_START": "Depart",
    "PICKUP": "Pick up",
    "DELIVERY": "Deliver",
    "DEPOT_END": "Return",
}
"""Stop kinds as a driver says them. A route ending somewhere else says "Finish"."""

REASONS: Mapping[str, tuple[str, str]] = {
    "NO_COMPATIBLE_VEHICLE": (
        "No truck with shifts has the tags this PO needs.",
        "Give a truck with shifts the needed tags, or remove the requirement from the PO.",
    ),
    "CAPACITY_EXCEEDED": (
        "The quantity is more than any suitable truck can carry.",
        "Split the PO into smaller ones, or add a bigger truck.",
    ),
    "ROUTE_DISTANCE_LIMIT_EXCEEDED": (
        "Every suitable truck would go over its distance limit, even with this PO alone.",
        "Raise a truck's distance limit, or add a truck without one.",
    ),
    "NO_COMPATIBLE_SHIFT_TIME": (
        "No shift is long enough, or at the right time, to do this PO and get back.",
        "Add or lengthen a shift around the PO's ready and due times.",
    ),
    "DEADLINE_IMPOSSIBLE_INDIVIDUALLY": (
        "It cannot meet its due time even planned on its own.",
        "Move the due time later or the ready time earlier, or start a shift earlier.",
    ),
    "INSUFFICIENT_COMBINED_FLEET_TIME": (
        "It fits on its own, but not together with the others: there is not enough truck "
        "time, capacity, or route allowance. Lower-priority POs are left out first.",
        "Add a truck or a shift, lengthen shifts, or raise this PO's priority.",
    ),
    "SOLVER_TIMEOUT": (
        "The search ran out of time.",
        "Raise the time limit on the Optimize page, or split a large scenario (for example "
        "one per day), and solve again.",
    ),
    "SOLVER_TIME_LIMIT_REACHED": (
        "The search stopped at its time limit while it was still fitting POs in, so some "
        "of the POs left out may fit after all.",
        "Raise the time limit or choose Thorough search on the Optimize page, or split a "
        "large scenario (for example one per day), and solve again.",
    ),
    "SOLVER_INFEASIBLE": (
        "No set of POs could be planned within the shifts, capacities, and due times.",
        "Check shifts, truck tags, and due times on the Review page.",
    ),
    "UNSCHEDULED": (
        "It was not planned.",
        "Check the Review page for warnings about this PO.",
    ),
}
"""Diagnostic code → (reason in plain words, suggested action)."""

REQUEST_LEVEL_ID = "REQUEST"
"""``task_id`` of diagnostics about the whole plan rather than one PO."""

MATRIX_SOURCE_LABELS: Mapping[str, str] = {
    "google_routes": "Google Maps",
    "deterministic_offline_fixture": "sample data in the scenario JSON",
    "fake": "offline test provider",
}
GOOGLE_MATRIX_SOURCE = "google_routes"
GOOGLE_ATTRIBUTION = "Google Maps"

MAPS_DIRECTIONS_URL = "https://www.google.com/maps/dir/?api=1"
MAX_LINK_WAYPOINTS = 9
MAX_LINK_LENGTH = 2_048


@dataclass(frozen=True, slots=True)
class PlanContext:
    """What the plan's IDs mean in this scenario."""

    timezone: str
    unit: str
    locations: Mapping[str, JsonObject]
    tasks: Mapping[str, JsonObject]
    vehicles: Mapping[str, JsonObject]
    shifts: Mapping[str, JsonObject]


def plan_context(scenario: Mapping[str, Any]) -> PlanContext:
    horizon = scenario.get("planning_horizon")
    timezone = scenario.get("timezone") or (
        horizon.get("timezone") if isinstance(horizon, dict) else None
    )
    return PlanContext(
        timezone=str(timezone or DEFAULT_TIMEZONE),
        unit=str(planner_defaults(scenario)["capacity_unit"]),
        locations=_by_id(scenario, "locations", "location_id"),
        tasks=_by_id(scenario, "tasks", "task_id"),
        vehicles=_by_id(scenario, "vehicles", "vehicle_id"),
        shifts=_by_id(scenario, "vehicle_shifts", "shift_id"),
    )


def _by_id(scenario: Mapping[str, Any], collection: str, key: str) -> dict[str, JsonObject]:
    return {str(row.get(key)): row for row in rows(scenario, collection) if row.get(key)}


def as_object(value: Any) -> JsonObject:
    """``value`` if it is a JSON object, else an empty one."""
    return value if isinstance(value, dict) else {}


def as_dicts(value: Any) -> list[JsonObject]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, dict)]


# --- names ---------------------------------------------------------------------------


def location_name(ctx: PlanContext, location_id: Any) -> str:
    location = ctx.locations.get(str(location_id))
    name = location.get("name") if location else None
    return str(name).strip() if name and str(name).strip() else str(location_id or "—")


def location_address(ctx: PlanContext, location_id: Any) -> str:
    """The address as the planner typed it (not Google's text)."""
    location = ctx.locations.get(str(location_id))
    return str(location.get("address") or "").strip() if location else ""


def truck_name(ctx: PlanContext, vehicle_id: Any) -> str:
    vehicle = ctx.vehicles.get(str(vehicle_id))
    name = vehicle.get("name") if vehicle else None
    return str(name).strip() if name and str(name).strip() else str(vehicle_id or "—")


def po_number(ctx: PlanContext, task_id: Any, fallback: Any = None) -> str:
    task = ctx.tasks.get(str(task_id))
    if task and task.get("po_number"):
        return str(task["po_number"])
    return str(fallback or task_id or "")


def priority_label(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "—"
    label = PRIORITY_LABELS.get(number, "")
    return f"{number} {label}".strip()


def quantity_text(value: Any, unit: str) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    shown = f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}".rstrip("0")
    return f"{shown} {unit}".strip()


# --- times ---------------------------------------------------------------------------


def local_day(value: Any, timezone: str) -> date | None:
    if not value:
        return None
    return to_local(str(value), timezone).date()


def local_datetime_text(value: Any, timezone: str) -> str:
    """``Mon 22 Jun 08:15`` in plant-local time; ``—`` when there is no time."""
    if value is None or value == "":
        return "—"
    return to_local(str(value), timezone).strftime("%a %d %b %H:%M")


def local_clock(value: Any, timezone: str, reference: date | None) -> str:
    """``08:15``, with ``(+1 day)`` when the time falls after the route's first day."""
    if value is None or value == "":
        return ""
    local = to_local(str(value), timezone)
    clock = local.strftime("%H:%M")
    if reference is None:
        return clock
    offset = (local.date() - reference).days
    if offset == 0:
        return clock
    return f"{clock} ({offset:+d} day{'s' if abs(offset) != 1 else ''})"


def duration_text(seconds: Any) -> str:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "—"
    return seconds_to_hmm(max(value, 0))


def km_text(meters: Any) -> str:
    try:
        return format_km(float(meters))
    except (TypeError, ValueError):
        return "—"


# --- summary -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanHeadline:
    level: str  # success, warning, or error
    sentence: str
    figures: Mapping[str, str]


def plan_headline(plan: Mapping[str, Any], ctx: PlanContext) -> PlanHeadline:
    """Status in plain words and the figures a planner checks first."""
    status = str(plan.get("status", ""))
    level, sentence = STATUS_TEXT.get(status, ("warning", f"Plan status: {status or 'unknown'}."))
    routes = as_dicts(plan.get("routes"))
    scheduled = len(as_dicts_or_ids(plan.get("scheduled_task_ids")))
    unscheduled = len(as_dicts_or_ids(plan.get("unscheduled_task_ids")))
    metrics = as_object(plan.get("metrics"))
    used = metrics.get("truck_shifts_used", len(routes)) if metrics else len(routes)
    available = metrics.get("truck_shifts_available") if metrics else None
    if available is None:
        available = sum(
            1
            for shift in ctx.shifts.values()
            if ctx.vehicles.get(str(shift.get("vehicle_id")), {}).get("enabled", True)
        )
    slacks = [
        int(stop["slack_seconds"])
        for route in routes
        for stop in as_dicts(route.get("stops"))
        if isinstance(stop.get("slack_seconds"), int | float)
    ]
    longest = metrics.get("longest_route_seconds") if metrics else None
    if longest is None:
        longest = max((route_elapsed_seconds(route) or 0 for route in routes), default=0)
    figures = {
        "Truck-shifts used": f"{used} of {available}",
        "POs planned": f"{scheduled} of {scheduled + unscheduled}",
        "Total distance": km_text(plan.get("total_distance_meters", 0)),
        "Driving time": duration_text(plan.get("total_driving_seconds", 0)),
        "Longest route": duration_text(longest),
        "Tightest slack": duration_text(min(slacks)) if slacks else "—",
    }
    return PlanHeadline(level=level, sentence=sentence, figures=figures)


def as_dicts_or_ids(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def route_elapsed_seconds(route: Mapping[str, Any]) -> int | None:
    total = route.get("total_duration_seconds")
    if isinstance(total, int | float):
        return int(total)
    stops = as_dicts(route.get("stops"))
    if len(stops) < 2:
        return None
    try:
        start = _instant(stops[0].get("departure_at"))
        end = _instant(stops[-1].get("arrival_at"))
    except ValueError:
        return None
    return int((end - start).total_seconds())


def _instant(value: Any) -> datetime:
    text = str(value or "").strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


# --- trucks and stops ----------------------------------------------------------------


def route_title(route: Mapping[str, Any], ctx: PlanContext) -> str:
    """``Truck 1 · Mon 22 Jun · 07:00-14:33``."""
    stops = as_dicts(route.get("stops"))
    name = truck_name(ctx, route.get("vehicle_id"))
    if not stops:
        return name
    first = stops[0].get("departure_at")
    reference = local_day(first, ctx.timezone)
    day = to_local(str(first), ctx.timezone).strftime("%a %d %b") if first else ""
    start = local_clock(first, ctx.timezone, reference)
    end = local_clock(stops[-1].get("arrival_at"), ctx.timezone, reference)
    return f"{name} · {day} · {start}-{end}"


def truck_rows(plan: Mapping[str, Any], ctx: PlanContext) -> list[JsonObject]:
    """One row per truck-shift used: when, how far, how long, how full."""
    result: list[JsonObject] = []
    for route in as_dicts(plan.get("routes")):
        stops = as_dicts(route.get("stops"))
        first = stops[0].get("departure_at") if stops else None
        last = stops[-1].get("arrival_at") if stops else None
        reference = local_day(first, ctx.timezone)
        vehicle = ctx.vehicles.get(str(route.get("vehicle_id")), {})
        capacity = vehicle.get("capacity")
        peak = quantity_text(route.get("peak_load", 0), "")
        peak_text = (
            f"{peak} of {quantity_text(capacity, ctx.unit)}" if capacity is not None else peak
        )
        result.append(
            {
                "Truck": truck_name(ctx, route.get("vehicle_id")),
                "Day": to_local(str(first), ctx.timezone).strftime("%a %d %b") if first else "—",
                "Start": local_clock(first, ctx.timezone, reference),
                "End": local_clock(last, ctx.timezone, reference),
                "POs": len({stop.get("task_id") for stop in stops if stop.get("task_id")}),
                "Distance": km_text(route.get("total_distance_meters", 0)),
                "Driving": duration_text(route.get("driving_seconds", 0)),
                "Service": duration_text(route.get("service_seconds", 0)),
                "Waiting": duration_text(route.get("waiting_seconds", 0)),
                "Peak load": peak_text,
            }
        )
    return result


def stop_action(stop: Mapping[str, Any], route: Mapping[str, Any]) -> str:
    kind = str(stop.get("kind", ""))
    if kind == "DEPOT_END":
        stops = as_dicts(route.get("stops"))
        start = stops[0].get("location_id") if stops else None
        return "Return" if stop.get("location_id") == start else "Finish"
    return ACTION_LABELS.get(kind, kind.title() or "—")


def stop_rows(route: Mapping[str, Any], ctx: PlanContext) -> list[JsonObject]:
    """The route's stops in order, with names, POs, and plant-local times."""
    stops = as_dicts(route.get("stops"))
    reference = local_day(stops[0].get("departure_at"), ctx.timezone) if stops else None
    result: list[JsonObject] = []
    for stop in stops:
        kind = str(stop.get("kind", ""))
        task_id = stop.get("task_id")
        task = ctx.tasks.get(str(task_id), {}) if task_id else {}
        slack = stop.get("slack_seconds")
        result.append(
            {
                "#": stop.get("sequence"),
                "Action": stop_action(stop, route),
                "Location": location_name(ctx, stop.get("location_id")),
                "PO": po_number(ctx, task_id) if task_id else "",
                "Quantity": quantity_text(task.get("quantity"), ctx.unit) if task_id else "",
                "Arrive": ""
                if kind == "DEPOT_START"
                else local_clock(stop.get("arrival_at"), ctx.timezone, reference),
                "Start": ""
                if kind in ("DEPOT_START", "DEPOT_END")
                else local_clock(stop.get("service_start_at"), ctx.timezone, reference),
                "Depart": ""
                if kind == "DEPOT_END"
                else local_clock(stop.get("departure_at"), ctx.timezone, reference),
                "Load after": quantity_text(stop.get("load_after", 0), ""),
                "Due by": local_datetime_text(stop.get("due_at"), ctx.timezone)
                if stop.get("due_at")
                else "",
                "Slack": duration_text(slack) if isinstance(slack, int | float) else "",
                "Leg distance": km_text(stop.get("distance_from_previous_meters", 0)),
                "Leg time": duration_text(stop.get("duration_from_previous_seconds", 0)),
            }
        )
    return result


# --- what was not planned ------------------------------------------------------------


def reason_for(diagnostic: Mapping[str, Any], ctx: PlanContext) -> tuple[str, str]:
    """(reason, suggested action) in plain words; unknown codes keep their message."""
    code = str(diagnostic.get("code", ""))
    reason, action = REASONS.get(
        code,
        (
            str(diagnostic.get("message") or "It was not planned."),
            "Check the Review page.",
        ),
    )
    if code == "DEADLINE_IMPOSSIBLE_INDIVIDUALLY" and diagnostic.get("estimated_completion_at"):
        finish = local_datetime_text(diagnostic["estimated_completion_at"], ctx.timezone)
        late = diagnostic.get("late_by_seconds")
        late_text = f", {duration_text(late)} late" if isinstance(late, int | float) else ""
        reason = f"{reason} The earliest it can be done is {finish}{late_text}."
    return reason, action


def unscheduled_rows(plan: Mapping[str, Any], ctx: PlanContext) -> list[JsonObject]:
    """POs left out, highest priority first, each with a reason and what to do."""
    by_task = {
        str(diagnostic.get("task_id")): diagnostic
        for diagnostic in as_dicts(plan.get("diagnostics"))
        if diagnostic.get("task_id") and diagnostic.get("task_id") != REQUEST_LEVEL_ID
    }
    task_ids = [str(value) for value in as_dicts_or_ids(plan.get("unscheduled_task_ids"))]
    task_ids += [task_id for task_id in by_task if task_id not in task_ids]
    result: list[tuple[int, str, JsonObject]] = []
    for task_id in task_ids:
        diagnostic = by_task.get(task_id, {"code": "UNSCHEDULED"})
        task = ctx.tasks.get(task_id, {})
        priority = diagnostic.get("priority") or task.get("priority") or 1
        reason, action = reason_for(diagnostic, ctx)
        due = diagnostic.get("due_at") or task.get("due_at")
        po = po_number(ctx, task_id, diagnostic.get("po_number"))
        result.append(
            (
                -_int(priority),
                po,
                {
                    "PO": po,
                    "Priority": priority_label(priority),
                    "Reason": reason,
                    "Due": local_datetime_text(due, ctx.timezone),
                    "Suggested action": action,
                },
            )
        )
    return [row for _, _, row in sorted(result, key=lambda item: (item[0], item[1]))]


def plan_problems(plan: Mapping[str, Any], ctx: PlanContext) -> list[tuple[str, str]]:
    """Problems with the whole plan rather than one PO, as (reason, suggested action)."""
    return [
        reason_for(diagnostic, ctx)
        for diagnostic in as_dicts(plan.get("diagnostics"))
        if diagnostic.get("task_id") == REQUEST_LEVEL_ID
    ]


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# --- settings and comparison -------------------------------------------------------


def matrix_source_label(source: Any) -> str:
    text = str(source or "")
    if not text:
        return "—"
    return MATRIX_SOURCE_LABELS.get(text, f"the scenario JSON ({text})")


def buffer_text(factor: Any) -> str:
    try:
        percent = round((float(factor) - 1) * 100)
    except (TypeError, ValueError):
        return "—"
    return "none" if percent <= 0 else f"{percent} %"


def plan_settings(plan: Mapping[str, Any], scenario: Mapping[str, Any]) -> list[JsonObject]:
    """How the plan was made, as Setting/Value rows (exports and the Results page)."""
    ctx = plan_context(scenario)
    options = plan.get("optimization_options")
    options = options if isinstance(options, dict) else {}
    matrix = as_object(plan.get("matrix"))
    objective = str(options.get("objective_mode", "MINIMIZE_TRUCKS"))
    name = scenario.get("name")
    settings: list[tuple[str, str]] = [
        ("Plan ID", str(plan.get("plan_id", ""))),
        ("Made", local_datetime_text(plan.get("created_at"), ctx.timezone)),
        (
            "Scenario",
            f"{scenario.get('scenario_id', '')}" + (f" ({name})" if name else ""),
        ),
        ("Outcome", STATUS_SHORT.get(str(plan.get("status")), str(plan.get("status", "")))),
        ("Objective", OBJECTIVES.get(objective, objective)),
        (
            "Search effort",
            SEARCH_EFFORTS.get(
                str(options.get("search_effort", "STANDARD")),
                str(options.get("search_effort", "")),
            ),
        ),
        (
            "Time limit",
            f"{options['time_limit_seconds']} s" if options.get("time_limit_seconds") else "—",
        ),
        ("Travel-time buffer", buffer_text(options.get("travel_time_factor", 1.0))),
        ("Cost of an extra truck", f"{options.get('extra_truck_cost_km', 1_000):,} km"),
        (
            "Balance strength",
            BALANCE_STRENGTHS.get(str(options.get("balance_strength", "MEDIUM")), "—"),
        ),
        ("Travel times from", matrix_source_label(matrix.get("source"))),
        (
            "Travel times calculated",
            local_datetime_text(matrix.get("created_at"), ctx.timezone),
        ),
        ("Times are in", ctx.timezone),
    ]
    if matrix.get("source") == GOOGLE_MATRIX_SOURCE:
        settings.append(("Travel times source", GOOGLE_ATTRIBUTION))
    return [{"Setting": key, "Value": value} for key, value in settings]


def comparison_rows(
    history: Sequence[Mapping[str, Any]],
    *,
    timezone: str,
    current: Mapping[str, Any] | None,
) -> list[JsonObject]:
    """Stored plans side by side, newest first, marked against the plan on screen."""
    current_id = current.get("plan_id") if current else None
    current_inputs = current.get("input_fingerprint") if current else None
    result: list[JsonObject] = []
    for summary in history:
        used = summary.get("truck_shifts_used", 0)
        available = summary.get("truck_shifts_available")
        objective = str(summary.get("objective_mode") or "MINIMIZE_TRUCKS")
        inputs = summary.get("input_fingerprint")
        if summary.get("plan_id") == current_id:
            same = "This plan"
        elif current_inputs and inputs:
            same = "Same" if inputs == current_inputs else "Different"
        else:
            same = "Unknown"
        longest_work = summary.get("longest_working_seconds")
        result.append(
            {
                "Made": local_datetime_text(summary.get("created_at"), timezone),
                "Objective": OBJECTIVES.get(objective, objective),
                "Search": SEARCH_EFFORTS.get(str(summary.get("search_effort") or "STANDARD"), "—"),
                "Buffer": buffer_text(summary.get("travel_time_factor") or 1.0),
                "Trucks used": f"{used} of {available}" if available is not None else str(used),
                "Distance": km_text(summary.get("total_distance_meters", 0)),
                "Longest route": duration_text(summary.get("longest_route_seconds"))
                if summary.get("longest_route_seconds") is not None
                else "—",
                "Longest working time": duration_text(longest_work)
                if longest_work is not None
                else "—",
                "Not planned": summary.get("unscheduled_count", 0),
                "Outcome": STATUS_SHORT.get(str(summary.get("status")), str(summary.get("status"))),
                "Inputs": same,
                "Plan ID": summary.get("plan_id"),
            }
        )
    return result


# --- Google Maps links and attribution -------------------------------------------------


def _map_point(location: Mapping[str, Any] | None) -> str | None:
    if not location:
        return None
    latitude, longitude = location.get("latitude"), location.get("longitude")
    if isinstance(latitude, int | float) and isinstance(longitude, int | float):
        return f"{float(latitude):.6f},{float(longitude):.6f}"
    address = str(location.get("address") or "").strip()
    return address or None


def route_map_points(route: Mapping[str, Any], ctx: PlanContext) -> list[str] | None:
    """The route's places in stop order, repeated places merged; ``None`` if one is unknown."""
    points: list[str] = []
    previous: Any = object()
    for stop in as_dicts(route.get("stops")):
        location_id = stop.get("location_id")
        if location_id == previous:
            continue
        previous = location_id
        point = _map_point(ctx.locations.get(str(location_id)))
        if point is None:
            return None
        points.append(point)
    return points


def _directions_url(points: Sequence[str]) -> str:
    url = (
        f"{MAPS_DIRECTIONS_URL}&origin={quote(points[0], safe=',')}"
        f"&destination={quote(points[-1], safe=',')}&travelmode=driving"
    )
    if len(points) > 2:
        url += "&waypoints=" + quote("|".join(points[1:-1]), safe=",")
    return url


def google_maps_links(route: Mapping[str, Any], ctx: PlanContext) -> list[str]:
    """Links that open the route in Google Maps, split so each fits Google's limits.

    Each link has at most nine waypoints and 2,048 characters; the next link starts
    where the previous one ended. A route with an unknown place gets no link.
    """
    points = route_map_points(route, ctx)
    if not points or len(points) < 2:
        return []
    links: list[str] = []
    start = 0
    while start < len(points) - 1:
        end = min(start + MAX_LINK_WAYPOINTS + 1, len(points) - 1)
        url = _directions_url(points[start : end + 1])
        while len(url) > MAX_LINK_LENGTH and end > start + 1:
            end -= 1
            url = _directions_url(points[start : end + 1])
        links.append(url)
        start = end
    return links


def uses_resolved_locations(scenario: Mapping[str, Any]) -> bool:
    """Whether any location's coordinates came from address resolution (decision D1)."""
    return any(
        location.get("geocode_source_fingerprint") for location in rows(scenario, "locations")
    )


def google_attribution(
    *, addresses: bool, travel_times: bool, google_configured: bool
) -> str | None:
    """The attribution line for Google content shown off a Google map, if any.

    Travel times carry their source exactly. Matched addresses come from Google when
    the backend has a Google key (the offline provider is for tests only).
    """
    shows_addresses = addresses and google_configured
    if shows_addresses and travel_times:
        return f"Matched addresses and travel times: {GOOGLE_ATTRIBUTION}"
    if shows_addresses:
        return f"Matched addresses: {GOOGLE_ATTRIBUTION}"
    if travel_times:
        return f"Travel times: {GOOGLE_ATTRIBUTION}"
    return None


def plan_uses_google_travel_times(plan: Mapping[str, Any] | None) -> bool:
    matrix = plan.get("matrix") if plan else None
    return isinstance(matrix, dict) and matrix.get("source") == GOOGLE_MATRIX_SOURCE
