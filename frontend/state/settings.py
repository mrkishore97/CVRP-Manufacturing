"""Scenario-level settings: name and ID, timezone, period, plant, and planner defaults.

Pure functions over the canonical scenario (plan §9.1). The period is stored as local
wall-clock text without an offset, which the backend reads in the plant timezone.
``planner_defaults`` is a frontend-only key the backend ignores: default service
minutes for new tasks and the label for load quantities.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from frontend.state.ids import is_valid_id
from frontend.state.scenario_state import (
    Row,
    Scenario,
    ScenarioEditError,
    find_row,
    row_ids,
    rows,
    upsert_location,
)
from frontend.state.timeutil import to_local, wall_clock_text

DEFAULT_TIMEZONE = "America/Toronto"
DEFAULT_PLANNER_DEFAULTS: Mapping[str, Any] = {
    "pickup_service_minutes": 15,
    "delivery_service_minutes": 15,
    "capacity_unit": "units",
}
MAX_SERVICE_MINUTES = 1_440


def timezone_choices(current: str | None = None) -> list[str]:
    """Every IANA zone, sorted, with ``current`` kept even if this machine lacks it."""
    zones = sorted(zone for zone in available_timezones() if "/" in zone or zone == "UTC")
    if current and current not in zones:
        zones.insert(0, current)
    return zones


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def planner_defaults(scenario: Mapping[str, Any]) -> dict[str, Any]:
    """The scenario's planner defaults, with the built-in ones filling any gap."""
    stored = scenario.get("planner_defaults")
    merged = dict(DEFAULT_PLANNER_DEFAULTS)
    if isinstance(stored, Mapping):
        merged.update({key: value for key, value in stored.items() if value is not None})
    return merged


def set_planner_defaults(
    scenario: Mapping[str, Any],
    *,
    pickup_service_minutes: int,
    delivery_service_minutes: int,
    capacity_unit: str,
) -> Scenario:
    for label, value in (
        ("Pickup service minutes", pickup_service_minutes),
        ("Delivery service minutes", delivery_service_minutes),
    ):
        if not 0 <= value <= MAX_SERVICE_MINUTES:
            raise ScenarioEditError(f"{label} must be between 0 and {MAX_SERVICE_MINUTES}.")
    unit = " ".join(capacity_unit.split()) or str(DEFAULT_PLANNER_DEFAULTS["capacity_unit"])
    updated = deepcopy(dict(scenario))
    updated["planner_defaults"] = {
        **(updated.get("planner_defaults") or {}),
        "pickup_service_minutes": int(pickup_service_minutes),
        "delivery_service_minutes": int(delivery_service_minutes),
        "capacity_unit": unit,
    }
    return updated


def period_bounds(scenario: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    """The planning period as plant-local times, or ``None`` if it cannot be read."""
    horizon = scenario.get("planning_horizon", scenario.get("horizon"))
    timezone = str(scenario.get("timezone") or DEFAULT_TIMEZONE)
    if not isinstance(horizon, Mapping) or not is_valid_timezone(timezone):
        return None
    try:
        return (
            to_local(str(horizon["start"]), timezone),
            to_local(str(horizon["end"]), timezone),
        )
    except (KeyError, ValueError):
        return None


def set_period(
    scenario: Mapping[str, Any],
    *,
    start_day: date,
    start_time: time,
    end_day: date,
    end_time: time,
) -> Scenario:
    """Set the period from date and time pickers, stored as local wall-clock text."""
    start = wall_clock_text(start_day, start_time)
    end = wall_clock_text(end_day, end_time)
    if datetime.fromisoformat(start) >= datetime.fromisoformat(end):
        raise ScenarioEditError("The planning period must end after it starts.")
    updated = deepcopy(dict(scenario))
    updated.pop("horizon", None)
    updated["planning_horizon"] = {"start": start, "end": end}
    return updated


def fitted_period(scenario: Mapping[str, Any]) -> tuple[str, str] | None:
    """Whole plant-local days covering every shift and every task window.

    "Fit to shifts and tasks" removes the commonest validation error: a shift or task
    outside the period. ``None`` when there is nothing to fit or a time is unreadable.
    """
    timezone = str(scenario.get("timezone") or DEFAULT_TIMEZONE)
    if not is_valid_timezone(timezone):
        return None
    values: list[str] = []
    for shift in rows(scenario, "vehicle_shifts"):
        values.extend(str(shift[key]) for key in ("start", "end") if shift.get(key))
    for task in rows(scenario, "tasks"):
        values.extend(str(task[key]) for key in ("ready_at", "due_at") if task.get(key))
    if not values:
        return None
    try:
        moments = [_local_moment(value, timezone) for value in values]
    except ValueError:
        return None
    first_day = min(moments).date()
    last = max(moments)
    end_day = last.date() + timedelta(days=1)
    return (
        wall_clock_text(first_day, time(0, 0)),
        wall_clock_text(end_day, time(0, 0)),
    )


def fit_period(scenario: Mapping[str, Any]) -> Scenario:
    fitted = fitted_period(scenario)
    if fitted is None:
        raise ScenarioEditError("There are no shifts or tasks with readable times to fit.")
    updated = deepcopy(dict(scenario))
    updated.pop("horizon", None)
    updated["planning_horizon"] = {"start": fitted[0], "end": fitted[1]}
    return updated


def plant_location(scenario: Mapping[str, Any]) -> Row | None:
    return find_row(scenario, "locations", str(scenario.get("plant_location_id", "PLANT")))


def set_plant(scenario: Mapping[str, Any], *, name: str, address: str) -> Scenario:
    """Create the plant location, or change its name and address.

    An address change clears the plant's resolution, as for any location.
    """
    clean_name = " ".join(name.split())
    clean_address = " ".join(address.split())
    if not clean_name or not clean_address:
        raise ScenarioEditError("The plant needs a name and an address.")
    plant_id = str(scenario.get("plant_location_id", "PLANT"))
    existing = find_row(scenario, "locations", plant_id)
    location: Row = existing or {"location_id": plant_id}
    location["name"] = clean_name
    location["address"] = clean_address
    updated = upsert_location(scenario, location)
    if "plant_location_id" not in updated:
        updated["plant_location_id"] = plant_id
    if existing is None:
        # A new plant goes first in the list, where planners look for it.
        locations = rows(updated, "locations")
        updated["locations"] = [locations[-1], *locations[:-1]]
    return updated


def choose_plant(scenario: Mapping[str, Any], location_id: str) -> Scenario:
    """Make an existing location the plant."""
    if location_id not in row_ids(scenario, "locations"):
        raise ScenarioEditError(f"Location {location_id} does not exist.")
    updated = deepcopy(dict(scenario))
    updated["plant_location_id"] = location_id
    return updated


def set_identity(scenario: Mapping[str, Any], *, name: str, scenario_id: str) -> Scenario:
    """Set the display name and the scenario ID (the ID under which it is saved)."""
    clean_id = scenario_id.strip()
    if not is_valid_id(clean_id):
        raise ScenarioEditError(
            f"{clean_id!r} is not a valid scenario ID: use letters, digits, '.', '_', ':' "
            "or '-', starting with a letter or digit."
        )
    updated = deepcopy(dict(scenario))
    clean_name = " ".join(name.split())
    if clean_name:
        updated["name"] = clean_name
    else:
        updated.pop("name", None)
    updated["scenario_id"] = clean_id
    return updated


def set_timezone(scenario: Mapping[str, Any], timezone: str) -> Scenario:
    if not is_valid_timezone(timezone):
        raise ScenarioEditError(f"{timezone} is not a known IANA timezone.")
    updated = deepcopy(dict(scenario))
    updated["timezone"] = timezone
    return updated


def _local_moment(value: str, timezone: str) -> datetime:
    """A stored time as plant-local; date-only values count as the start of that day."""
    text = value.strip()
    if len(text) == 10:
        parsed_day = date.fromisoformat(text)
        return datetime.combine(parsed_day, time(0, 0), tzinfo=ZoneInfo(timezone))
    return to_local(text, timezone)
