"""Fleet: trucks, their shifts, and the shift generator (plan §9.3).

Pure functions over the canonical scenario; the Fleet page only renders them.
Capacities allow up to three decimals; durations are entered as h:mm and stored in
seconds; distances are entered in kilometres and stored in metres. Shift times are
stored as plant-local wall-clock text, which the backend reads in the plant timezone.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from frontend.state.ids import is_valid_id, suggest_shift_id, suggest_vehicle_id, unique_id
from frontend.state.scenario_state import (
    Row,
    Scenario,
    ScenarioEditError,
    find_row,
    row_ids,
    rows,
    upsert_shift,
    upsert_vehicle,
)
from frontend.state.settings import DEFAULT_TIMEZONE, extend_period
from frontend.state.timeutil import to_local, wall_clock_text
from frontend.state.units import format_km, km_to_meters, seconds_to_hmm

WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WORKING_DAYS = frozenset(range(5))


def plant_id(scenario: Mapping[str, Any]) -> str:
    return str(scenario.get("plant_location_id", "PLANT"))


def timezone_of(scenario: Mapping[str, Any]) -> str:
    return str(scenario.get("timezone") or DEFAULT_TIMEZONE)


# --- trucks -------------------------------------------------------------------------


def parse_tags(value: str | Iterable[str] | None) -> list[str]:
    """Tags as the backend stores them: trimmed, upper-case, unique, sorted."""
    if value is None:
        return []
    parts = value.split(",") if isinstance(value, str) else [str(part) for part in value]
    return sorted({part.strip().upper() for part in parts if part.strip()})


def fleet_tags(scenario: Mapping[str, Any]) -> list[str]:
    """Every tag any truck has, for the task form's tag picker."""
    tags: set[str] = set()
    for vehicle in rows(scenario, "vehicles"):
        tags.update(parse_tags(vehicle.get("tags")))
    return sorted(tags)


def capacity_value(value: float | int | str | Decimal) -> int | float:
    """A positive load with at most three decimals, as a JSON number."""
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ScenarioEditError("Capacity must be a number.") from None
    if not number.is_finite() or number <= 0:
        raise ScenarioEditError("Capacity must be more than zero.")
    number = number.normalize()
    exponent = number.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > 3:
        raise ScenarioEditError("Capacity may have at most three decimal places.")
    return int(number) if number == number.to_integral_value() else float(number)


def _limits(
    max_duration_seconds: int | None, max_distance_km: float | None
) -> dict[str, int | None]:
    if max_duration_seconds is not None and max_duration_seconds <= 0:
        raise ScenarioEditError("A maximum route duration must be longer than 0:00.")
    if max_distance_km is not None and max_distance_km <= 0:
        raise ScenarioEditError("A maximum route distance must be more than 0 km.")
    return {
        "maximum_route_duration_seconds": max_duration_seconds,
        "maximum_route_distance_meters": (
            km_to_meters(max_distance_km) if max_distance_km is not None else None
        ),
    }


def _vehicle_row(
    vehicle: Row,
    *,
    name: str,
    capacity: float | int | str | Decimal,
    enabled: bool,
    tags: str | Iterable[str] | None,
    max_duration_seconds: int | None,
    max_distance_km: float | None,
) -> Row:
    clean_name = " ".join(name.split())
    if not clean_name:
        raise ScenarioEditError("Enter a name for the truck.")
    vehicle["name"] = clean_name
    vehicle["capacity"] = capacity_value(capacity)
    vehicle["enabled"] = bool(enabled)
    tag_list = parse_tags(tags)
    if tag_list:
        vehicle["tags"] = tag_list
    else:
        vehicle.pop("tags", None)
    for key, value in _limits(max_duration_seconds, max_distance_km).items():
        if value is None:
            vehicle.pop(key, None)
        else:
            vehicle[key] = value
    return vehicle


def add_vehicle(
    scenario: Mapping[str, Any],
    *,
    name: str,
    capacity: float | int | str | Decimal,
    enabled: bool = True,
    tags: str | Iterable[str] | None = None,
    max_duration_seconds: int | None = None,
    max_distance_km: float | None = None,
    vehicle_id: str | None = None,
) -> tuple[Scenario, str]:
    existing = row_ids(scenario, "vehicles")
    chosen = (vehicle_id or "").strip() or suggest_vehicle_id(name, existing)
    if not is_valid_id(chosen):
        raise ScenarioEditError(f"{chosen!r} is not a valid truck ID.")
    if chosen in existing:
        raise ScenarioEditError(f"Truck ID {chosen} is already used.")
    vehicle = _vehicle_row(
        {"vehicle_id": chosen},
        name=name,
        capacity=capacity,
        enabled=enabled,
        tags=tags,
        max_duration_seconds=max_duration_seconds,
        max_distance_km=max_distance_km,
    )
    return upsert_vehicle(scenario, vehicle), chosen


def edit_vehicle(
    scenario: Mapping[str, Any],
    vehicle_id: str,
    *,
    name: str,
    capacity: float | int | str | Decimal,
    enabled: bool,
    tags: str | Iterable[str] | None,
    max_duration_seconds: int | None,
    max_distance_km: float | None,
) -> Scenario:
    vehicle = find_row(scenario, "vehicles", vehicle_id)
    if vehicle is None:
        raise ScenarioEditError(f"Truck {vehicle_id} does not exist.")
    return upsert_vehicle(
        scenario,
        _vehicle_row(
            vehicle,
            name=name,
            capacity=capacity,
            enabled=enabled,
            tags=tags,
            max_duration_seconds=max_duration_seconds,
            max_distance_km=max_distance_km,
        ),
    )


def duplicate_vehicle(scenario: Mapping[str, Any], vehicle_id: str) -> tuple[Scenario, str]:
    """A copy of the truck with a new ID and "(copy)" name; its shifts are not copied."""
    vehicle = find_row(scenario, "vehicles", vehicle_id)
    if vehicle is None:
        raise ScenarioEditError(f"Truck {vehicle_id} does not exist.")
    new_id = unique_id(vehicle_id, row_ids(scenario, "vehicles"))
    vehicle["vehicle_id"] = new_id
    vehicle["name"] = f"{vehicle.get('name', vehicle_id)} (copy)"
    return upsert_vehicle(scenario, vehicle), new_id


def vehicle_label(scenario: Mapping[str, Any], vehicle_id: str) -> str:
    vehicle = find_row(scenario, "vehicles", vehicle_id)
    name = vehicle.get("name") if vehicle else None
    return f"{name} ({vehicle_id})" if name else vehicle_id


def vehicle_table_rows(scenario: Mapping[str, Any], unit: str) -> list[dict[str, Any]]:
    shift_counts: dict[str, int] = {}
    for shift in rows(scenario, "vehicle_shifts"):
        key = str(shift.get("vehicle_id"))
        shift_counts[key] = shift_counts.get(key, 0) + 1
    result = []
    for vehicle in rows(scenario, "vehicles"):
        vehicle_id = str(vehicle.get("vehicle_id"))
        duration = vehicle.get("maximum_route_duration_seconds")
        distance = vehicle.get("maximum_route_distance_meters")
        result.append(
            {
                "Name": vehicle.get("name"),
                "Capacity": f"{vehicle.get('capacity')} {unit}",
                "Enabled": "Yes" if vehicle.get("enabled", True) else "No",
                "Tags": ", ".join(parse_tags(vehicle.get("tags"))) or "—",
                "Max route time": seconds_to_hmm(duration) if duration else "—",
                "Max route distance": format_km(distance, decimals=0) if distance else "—",
                "Shifts": shift_counts.get(vehicle_id, 0),
                "ID": vehicle_id,
            }
        )
    return result


# --- shifts -------------------------------------------------------------------------


def shift_times(day: date, start: time, end: time) -> tuple[str, str]:
    """Local wall-clock text; an end at or before the start is on the next day."""
    end_day = day + timedelta(days=1) if end <= start else day
    return wall_clock_text(day, start), wall_clock_text(end_day, end)


def _shift_row(
    scenario: Mapping[str, Any],
    shift: Row,
    *,
    vehicle_id: str,
    day: date,
    start: time,
    end: time,
    start_location_id: str | None,
    end_location_id: str | None,
    max_duration_seconds: int | None,
) -> Row:
    if vehicle_id not in row_ids(scenario, "vehicles"):
        raise ScenarioEditError(f"Truck {vehicle_id} does not exist.")
    locations = set(row_ids(scenario, "locations"))
    plant = plant_id(scenario)
    start_at = start_location_id or plant
    end_at = end_location_id or plant
    for label, location_id in (("start", start_at), ("end", end_at)):
        if location_id not in locations:
            raise ScenarioEditError(f"The {label} location {location_id} does not exist.")
    if max_duration_seconds is not None and max_duration_seconds <= 0:
        raise ScenarioEditError("A maximum route duration must be longer than 0:00.")
    start_text, end_text = shift_times(day, start, end)
    shift.update({"vehicle_id": vehicle_id, "start": start_text, "end": end_text})
    # The plant is the backend default for both ends; keep the JSON as short as before.
    for key, value in (("start_location_id", start_at), ("end_location_id", end_at)):
        if value == plant and key not in shift:
            continue
        shift[key] = value
    if max_duration_seconds is None:
        shift.pop("maximum_route_duration_seconds", None)
    else:
        shift["maximum_route_duration_seconds"] = max_duration_seconds
    return shift


@dataclass(frozen=True, slots=True)
class ShiftEdit:
    scenario: Scenario
    shift_id: str
    period_extended: bool


def add_shift(
    scenario: Mapping[str, Any],
    *,
    vehicle_id: str,
    day: date,
    start: time,
    end: time,
    start_location_id: str | None = None,
    end_location_id: str | None = None,
    max_duration_seconds: int | None = None,
    shift_id: str | None = None,
) -> ShiftEdit:
    existing = row_ids(scenario, "vehicle_shifts")
    chosen = (shift_id or "").strip() or suggest_shift_id(vehicle_id, day, existing)
    if not is_valid_id(chosen):
        raise ScenarioEditError(f"{chosen!r} is not a valid shift ID.")
    if chosen in existing:
        raise ScenarioEditError(f"Shift ID {chosen} is already used.")
    shift = _shift_row(
        scenario,
        {"shift_id": chosen},
        vehicle_id=vehicle_id,
        day=day,
        start=start,
        end=end,
        start_location_id=start_location_id,
        end_location_id=end_location_id,
        max_duration_seconds=max_duration_seconds,
    )
    updated, extended = extend_period(upsert_shift(scenario, shift), [shift["start"], shift["end"]])
    return ShiftEdit(updated, chosen, extended)


def edit_shift(
    scenario: Mapping[str, Any],
    shift_id: str,
    *,
    vehicle_id: str,
    day: date,
    start: time,
    end: time,
    start_location_id: str | None,
    end_location_id: str | None,
    max_duration_seconds: int | None,
) -> ShiftEdit:
    shift = find_row(scenario, "vehicle_shifts", shift_id)
    if shift is None:
        raise ScenarioEditError(f"Shift {shift_id} does not exist.")
    shift = _shift_row(
        scenario,
        shift,
        vehicle_id=vehicle_id,
        day=day,
        start=start,
        end=end,
        start_location_id=start_location_id,
        end_location_id=end_location_id,
        max_duration_seconds=max_duration_seconds,
    )
    updated, extended = extend_period(upsert_shift(scenario, shift), [shift["start"], shift["end"]])
    return ShiftEdit(updated, shift_id, extended)


def duplicate_shift(scenario: Mapping[str, Any], shift_id: str) -> ShiftEdit:
    """The same truck and hours on the next day — the commonest copy."""
    shift = find_row(scenario, "vehicle_shifts", shift_id)
    if shift is None:
        raise ScenarioEditError(f"Shift {shift_id} does not exist.")
    timezone = timezone_of(scenario)
    start = to_local(str(shift["start"]), timezone) + timedelta(days=1)
    end = to_local(str(shift["end"]), timezone) + timedelta(days=1)
    vehicle_id = str(shift.get("vehicle_id"))
    new_id = suggest_shift_id(vehicle_id, start.date(), row_ids(scenario, "vehicle_shifts"))
    shift["shift_id"] = new_id
    shift["start"] = wall_clock_text(start.date(), start.time())
    shift["end"] = wall_clock_text(end.date(), end.time())
    updated, extended = extend_period(upsert_shift(scenario, shift), [shift["start"], shift["end"]])
    return ShiftEdit(updated, new_id, extended)


def shift_bounds(shift: Mapping[str, Any], timezone: str) -> tuple[datetime, datetime] | None:
    try:
        return to_local(str(shift["start"]), timezone), to_local(str(shift["end"]), timezone)
    except (KeyError, ValueError):
        return None


def overlapping_shift_ids(scenario: Mapping[str, Any]) -> dict[str, str]:
    """Shift ID → the earlier shift of the same truck that it overlaps."""
    timezone = timezone_of(scenario)
    by_vehicle: dict[str, list[tuple[datetime, datetime, str]]] = {}
    for shift in rows(scenario, "vehicle_shifts"):
        bounds = shift_bounds(shift, timezone)
        if bounds is not None:
            by_vehicle.setdefault(str(shift.get("vehicle_id")), []).append(
                (bounds[0], bounds[1], str(shift.get("shift_id")))
            )
    overlaps: dict[str, str] = {}
    for intervals in by_vehicle.values():
        intervals.sort()
        latest = intervals[0]
        for current in intervals[1:]:
            if latest[1] > current[0]:
                overlaps[current[2]] = latest[2]
            if current[1] > latest[1]:
                latest = current
    return overlaps


def location_name(scenario: Mapping[str, Any], location_id: str) -> str:
    location = find_row(scenario, "locations", location_id)
    return str(location.get("name") or location_id) if location else location_id


def shift_table_rows(scenario: Mapping[str, Any]) -> list[dict[str, Any]]:
    timezone = timezone_of(scenario)
    plant = plant_id(scenario)
    overlaps = overlapping_shift_ids(scenario)
    result = []
    for shift in rows(scenario, "vehicle_shifts"):
        shift_id = str(shift.get("shift_id"))
        bounds = shift_bounds(shift, timezone)
        limit = shift.get("maximum_route_duration_seconds")
        result.append(
            {
                "Truck": vehicle_label(scenario, str(shift.get("vehicle_id"))),
                "Date": bounds[0].strftime("%a %Y-%m-%d") if bounds else "—",
                "Start": bounds[0].strftime("%H:%M") if bounds else str(shift.get("start")),
                "End": _end_label(bounds) if bounds else str(shift.get("end")),
                "Starts at": location_name(scenario, str(shift.get("start_location_id", plant))),
                "Ends at": location_name(scenario, str(shift.get("end_location_id", plant))),
                "Max route time": seconds_to_hmm(limit) if limit else "—",
                "Check": f"Overlaps {overlaps[shift_id]}" if shift_id in overlaps else "",
                "ID": shift_id,
            }
        )
    return result


def _end_label(bounds: tuple[datetime, datetime]) -> str:
    start, end = bounds
    days = (end.date() - start.date()).days
    return (
        end.strftime("%H:%M")
        + (f" (+{days} day)" if days == 1 else "")
        + (f" (+{days} days)" if days > 1 else "")
    )


# --- shift generator ----------------------------------------------------------------


class GeneratedStatus(StrEnum):
    NEW = "New"
    EXISTS = "Already exists"
    OVERLAPS = "Overlaps a shift"


@dataclass(frozen=True, slots=True)
class GeneratedShift:
    shift_id: str
    vehicle_id: str
    day: date
    start: str
    end: str
    status: GeneratedStatus
    note: str = ""


def generate_shifts(
    scenario: Mapping[str, Any],
    *,
    vehicle_ids: Sequence[str],
    first_day: date,
    last_day: date,
    weekdays: Iterable[int],
    start: time,
    end: time,
) -> list[GeneratedShift]:
    """Preview: one shift per truck per chosen weekday, with existing and overlaps flagged.

    A shift is "already exists" when the truck has one with the same start and end,
    and "overlaps" when it collides with another shift of that truck. Only new shifts
    are applied. IDs follow the fixture convention and are unique.
    """
    if last_day < first_day:
        raise ScenarioEditError("The last day must not be before the first day.")
    if (last_day - first_day).days > 366:
        raise ScenarioEditError("Generate at most a year of shifts at once.")
    chosen_weekdays = set(weekdays)
    if not chosen_weekdays:
        raise ScenarioEditError("Choose at least one weekday.")
    known = set(row_ids(scenario, "vehicles"))
    missing = [vehicle_id for vehicle_id in vehicle_ids if vehicle_id not in known]
    if missing or not vehicle_ids:
        raise ScenarioEditError("Choose at least one existing truck.")
    timezone = timezone_of(scenario)
    taken = list(row_ids(scenario, "vehicle_shifts"))
    existing: dict[str, list[tuple[datetime, datetime, str]]] = {}
    for shift in rows(scenario, "vehicle_shifts"):
        bounds = shift_bounds(shift, timezone)
        if bounds is not None:
            existing.setdefault(str(shift.get("vehicle_id")), []).append(
                (bounds[0], bounds[1], str(shift.get("shift_id")))
            )

    generated: list[GeneratedShift] = []
    day = first_day
    while day <= last_day:
        if day.weekday() in chosen_weekdays:
            start_text, end_text = shift_times(day, start, end)
            start_at, end_at = to_local(start_text, timezone), to_local(end_text, timezone)
            for vehicle_id in vehicle_ids:
                status, note = GeneratedStatus.NEW, ""
                for other_start, other_end, other_id in existing.get(vehicle_id, []):
                    if (other_start, other_end) == (start_at, end_at):
                        status, note = GeneratedStatus.EXISTS, other_id
                        break
                    if other_start < end_at and start_at < other_end:
                        status, note = GeneratedStatus.OVERLAPS, other_id
                shift_id = ""
                if status is GeneratedStatus.NEW:
                    shift_id = suggest_shift_id(vehicle_id, day, taken)
                    taken.append(shift_id)
                    existing.setdefault(vehicle_id, []).append((start_at, end_at, shift_id))
                generated.append(
                    GeneratedShift(shift_id, vehicle_id, day, start_text, end_text, status, note)
                )
        day += timedelta(days=1)
    return generated


@dataclass(frozen=True, slots=True)
class GeneratorOutcome:
    scenario: Scenario
    added: tuple[str, ...]
    skipped: int
    period_extended: bool


def apply_generated_shifts(
    scenario: Mapping[str, Any],
    generated: Sequence[GeneratedShift],
    *,
    start_location_id: str | None = None,
    end_location_id: str | None = None,
    max_duration_seconds: int | None = None,
) -> GeneratorOutcome:
    """Add the new shifts (all or none); existing and overlapping ones are skipped."""
    updated: Scenario = dict(scenario)
    added: list[str] = []
    for item in generated:
        if item.status is not GeneratedStatus.NEW:
            continue
        start_at = to_local(item.start, timezone_of(scenario))
        end_at = to_local(item.end, timezone_of(scenario))
        shift = _shift_row(
            updated,
            {"shift_id": item.shift_id},
            vehicle_id=item.vehicle_id,
            day=start_at.date(),
            start=start_at.time().replace(tzinfo=None),
            end=end_at.time().replace(tzinfo=None),
            start_location_id=start_location_id,
            end_location_id=end_location_id,
            max_duration_seconds=max_duration_seconds,
        )
        if item.shift_id in row_ids(updated, "vehicle_shifts"):
            raise ScenarioEditError(f"Shift ID {item.shift_id} is already used.")
        updated = upsert_shift(updated, shift)
        added.append(item.shift_id)
    times = [
        value
        for item in generated
        if item.status is GeneratedStatus.NEW
        for value in (item.start, item.end)
    ]
    updated, extended = extend_period(updated, times)
    return GeneratorOutcome(
        scenario=updated,
        added=tuple(added),
        skipped=sum(item.status is not GeneratedStatus.NEW for item in generated),
        period_extended=extended,
    )
