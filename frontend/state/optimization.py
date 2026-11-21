"""Optimization options: what the Optimize page offers and how it is stored (plan §9.7).

Options live in the scenario as ``optimization_options``. Only values that differ from
the defaults are written, so a scenario whose options are all default keeps the Version
1.0 JSON shape and is solved exactly as before. The time limit's default is the
server's, so it is stored only when the planner picks another value.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from frontend.state.scenario_state import Scenario, ScenarioEditError
from frontend.state.units import seconds_to_hmm

MINIMIZE_TRUCKS, MINIMIZE_TRAVEL, BALANCE_WORKLOAD = (
    "MINIMIZE_TRUCKS",
    "MINIMIZE_TRAVEL",
    "BALANCE_WORKLOAD",
)
OBJECTIVES: Mapping[str, str] = {
    MINIMIZE_TRUCKS: "Fewest trucks",
    MINIMIZE_TRAVEL: "Least travel",
    BALANCE_WORKLOAD: "Balanced workload",
}
OBJECTIVE_HELP: Mapping[str, str] = {
    MINIMIZE_TRUCKS: (
        "Puts the work on as few trucks as possible; another truck is used only when it "
        "saves more than the cost of an extra truck. This is how Version 1.0 planned."
    ),
    MINIMIZE_TRAVEL: (
        "Drives the fewest kilometres in total, using another truck whenever that is shorter."
    ),
    BALANCE_WORKLOAD: (
        "Spreads the work so no driver carries a much longer day than the others, at the "
        "cost of some extra kilometres. An empty truck is never sent out."
    ),
}
STANDARD, THOROUGH = "STANDARD", "THOROUGH"
SEARCH_EFFORTS: Mapping[str, str] = {
    STANDARD: "Standard",
    THOROUGH: "Thorough",
}
SEARCH_EFFORT_HELP: Mapping[str, str] = {
    STANDARD: "Returns as soon as it has a good plan, usually within a second or two.",
    THOROUGH: "Keeps improving the plan until the time limit, so it always takes that long.",
}
BALANCE_STRENGTHS: Mapping[str, str] = {
    "LIGHT": "Light",
    "MEDIUM": "Medium",
    "STRONG": "Strong",
}
DEFAULTS: Mapping[str, Any] = {
    "objective_mode": MINIMIZE_TRUCKS,
    "search_effort": STANDARD,
    "travel_time_factor": 1.0,
    "extra_truck_cost_km": 1_000,
    "balance_strength": "MEDIUM",
}
MAX_BUFFER_PERCENT = 100
MAX_EXTRA_TRUCK_COST_KM = 100_000
HARD_CONSTRAINTS_NOTE = (
    "No setting here relaxes a hard rule: truck capacity, deadlines, shifts, truck tags, "
    "and route time and distance limits always hold."
)


def stored_options(scenario: Mapping[str, Any]) -> dict[str, Any]:
    value = scenario.get("optimization_options")
    return dict(value) if isinstance(value, Mapping) else {}


def current_options(scenario: Mapping[str, Any], *, default_time_limit: int) -> dict[str, Any]:
    """Every option with its value, defaults filled in."""
    options = {**DEFAULTS, "time_limit_seconds": default_time_limit}
    options.update(
        {key: value for key, value in stored_options(scenario).items() if value is not None}
    )
    return options


def buffer_percent(factor: Any) -> int:
    try:
        return round((float(factor) - 1.0) * 100)
    except (TypeError, ValueError):
        return 0


def set_options(
    scenario: Mapping[str, Any],
    *,
    objective_mode: str,
    search_effort: str,
    time_limit_seconds: int,
    buffer_percent: int,
    extra_truck_cost_km: int,
    balance_strength: str,
    default_time_limit: int,
    max_time_limit: int,
) -> Scenario:
    """Store the options; values equal to the defaults are left out."""
    if objective_mode not in OBJECTIVES:
        raise ScenarioEditError(f"Unknown objective {objective_mode!r}.")
    if search_effort not in SEARCH_EFFORTS:
        raise ScenarioEditError(f"Unknown search effort {search_effort!r}.")
    if balance_strength not in BALANCE_STRENGTHS:
        raise ScenarioEditError(f"Unknown balance strength {balance_strength!r}.")
    if not 1 <= time_limit_seconds <= max_time_limit:
        raise ScenarioEditError(f"The time limit must be 1 to {max_time_limit} seconds.")
    if not 0 <= buffer_percent <= MAX_BUFFER_PERCENT:
        raise ScenarioEditError(f"The travel-time buffer must be 0 to {MAX_BUFFER_PERCENT} %.")
    if not 0 <= extra_truck_cost_km <= MAX_EXTRA_TRUCK_COST_KM:
        raise ScenarioEditError(
            f"The cost of an extra truck must be 0 to {MAX_EXTRA_TRUCK_COST_KM:,} km."
        )
    chosen: dict[str, Any] = {
        "objective_mode": objective_mode,
        "search_effort": search_effort,
        "travel_time_factor": round(1.0 + buffer_percent / 100, 2),
        "extra_truck_cost_km": int(extra_truck_cost_km),
        "balance_strength": balance_strength,
    }
    stored = {key: value for key, value in chosen.items() if value != DEFAULTS[key]}
    if time_limit_seconds != default_time_limit:
        stored["time_limit_seconds"] = int(time_limit_seconds)
    updated = deepcopy(dict(scenario))
    if stored:
        updated["optimization_options"] = stored
    else:
        updated.pop("optimization_options", None)
    return updated


def effective_time_limit(
    scenario: Mapping[str, Any], *, default_time_limit: int, max_time_limit: int
) -> int:
    limit = current_options(scenario, default_time_limit=default_time_limit)["time_limit_seconds"]
    try:
        return max(1, min(int(limit), max_time_limit))
    except (TypeError, ValueError):
        return default_time_limit


def options_summary(options: Mapping[str, Any] | None) -> str:
    """One line describing how a plan was made, from the options recorded on it."""
    if not options:
        return "Fewest trucks, standard search (Version 1.0 settings)."
    options = {**DEFAULTS, **{key: value for key, value in options.items() if value is not None}}
    parts = [
        OBJECTIVES.get(str(options.get("objective_mode")), str(options.get("objective_mode"))),
        f"{SEARCH_EFFORTS.get(str(options.get('search_effort')), 'Standard').lower()} search",
    ]
    if options.get("time_limit_seconds"):
        parts.append(f"time limit {options['time_limit_seconds']} s")
    percent = buffer_percent(options.get("travel_time_factor", 1.0))
    parts.append(f"travel-time buffer {percent} %" if percent else "no travel-time buffer")
    if options.get("objective_mode") == BALANCE_WORKLOAD:
        strength = BALANCE_STRENGTHS.get(str(options.get("balance_strength")), "Medium")
        parts.append(f"{strength.lower()} balance")
    if options.get("objective_mode") == MINIMIZE_TRUCKS and options.get(
        "extra_truck_cost_km"
    ) not in (None, DEFAULTS["extra_truck_cost_km"]):
        parts.append(f"extra truck worth {int(options['extra_truck_cost_km']):,} km")
    return ", ".join(parts) + "."


def plan_figures(plan: Mapping[str, Any]) -> dict[str, str]:
    """The headline figures of a plan, for comparing settings."""
    metrics = plan.get("metrics") if isinstance(plan.get("metrics"), Mapping) else {}
    assert isinstance(metrics, Mapping)
    used = metrics.get("truck_shifts_used", len(plan.get("routes", []) or []))
    available = metrics.get("truck_shifts_available")
    longest = metrics.get("longest_route_seconds")
    working = metrics.get("longest_working_seconds")
    return {
        "Truck-shifts used": f"{used} of {available}" if available is not None else str(used),
        "Total distance": f"{float(plan.get('total_distance_meters', 0) or 0) / 1000:,.1f} km",
        "Longest route": seconds_to_hmm(longest) if isinstance(longest, int) else "—",
        "Longest working time": seconds_to_hmm(working) if isinstance(working, int) else "—",
    }


def solve_timeout_seconds(time_limit_seconds: int) -> float:
    """Wait long enough for the strict and the partial-plan attempt (plan §14, M0)."""
    return 2 * time_limit_seconds + 20
