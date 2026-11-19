"""The canonical scenario: one dictionary in the public planning-payload shape.

Forms and the JSON view both edit this one object through the pure functions below.
Every function returns a new scenario and never mutates its input. The functions own
referential integrity: deleting something still referenced is refused with the list of
dependants, renaming an ID cascades to every reference, and changing an address clears
that location's derived geocoding fields.

The scenario never holds the active travel-time matrix; derived artifacts live beside
it (see ``workspace.py``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from frontend.state.ids import is_valid_id

Scenario = dict[str, Any]
Row = dict[str, Any]

COLLECTION_ID_FIELDS: Mapping[str, str] = {
    "locations": "location_id",
    "vehicles": "vehicle_id",
    "vehicle_shifts": "shift_id",
    "tasks": "task_id",
}
DERIVED_LOCATION_FIELDS: tuple[str, ...] = (
    "formatted_address",
    "place_id",
    "latitude",
    "longitude",
    "geocode_status",
    "geocode_warning",
    "geocode_source_fingerprint",
    "geocoded_at",
    "geocode_location_type",
    "geocode_partial_match",
    "geocode_confirmed",
)
"""Location fields produced by address resolution rather than typed by the planner."""

PLANNER_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "scenario_id",
    "name",
    "timezone",
    "planning_horizon",
    "plant_location_id",
    "locations",
    "vehicles",
    "vehicle_shifts",
    "tasks",
    "routing_options",
    "optimization_options",
    "planner_defaults",
)


class ScenarioEditError(ValueError):
    """An edit that would break the scenario; the scenario is left unchanged."""


@dataclass(frozen=True, slots=True)
class Dependant:
    """Something that refers to the item being deleted."""

    kind: str  # "task", "shift", "vehicle", or "plant"
    item_id: str


class ReferencedItemError(ScenarioEditError):
    """Deletion refused because other items still refer to the item."""

    def __init__(self, label: str, dependants: tuple[Dependant, ...]) -> None:
        self.dependants = dependants
        super().__init__(f"{label} is {describe_dependants(dependants)}.")


def describe_dependants(dependants: Iterable[Dependant]) -> str:
    """``used by 3 tasks and 2 shifts``; ``the plant`` when it is the plant."""
    counts: dict[str, int] = {}
    is_plant = False
    for dependant in dependants:
        if dependant.kind == "plant":
            is_plant = True
        else:
            counts[dependant.kind] = counts.get(dependant.kind, 0) + 1
    parts = [f"{count} {kind}{'' if count == 1 else 's'}" for kind, count in counts.items()]
    phrases: list[str] = []
    if is_plant:
        phrases.append("the plant")
    if parts:
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        phrases.append(f"used by {joined}")
    return " and ".join(phrases) if phrases else "not used"


def new_scenario(
    *,
    scenario_id: str = "NEW-SCENARIO",
    name: str | None = None,
    timezone: str = "America/Toronto",
    plant_location_id: str = "PLANT",
    start_day: date | None = None,
    days: int = 1,
) -> Scenario:
    """An empty scenario with a planning period of whole local days."""
    if not is_valid_id(scenario_id):
        raise ScenarioEditError(f"{scenario_id!r} is not a valid scenario ID.")
    if days <= 0:
        raise ScenarioEditError("The planning period must cover at least one day.")
    first_day = start_day or date.today()
    scenario: Scenario = {"scenario_id": scenario_id}
    if name:
        scenario["name"] = name
    scenario.update(
        {
            "timezone": timezone,
            "planning_horizon": {
                "start": f"{first_day.isoformat()}T00:00:00",
                "end": f"{(first_day + timedelta(days=days)).isoformat()}T00:00:00",
            },
            "plant_location_id": plant_location_id,
            "locations": [],
            "vehicles": [],
            "vehicle_shifts": [],
            "tasks": [],
        }
    )
    return scenario


def rows(scenario: Mapping[str, Any], collection: str) -> list[Row]:
    """The dictionaries in one collection; anything malformed is skipped."""
    _id_field(collection)
    values = scenario.get(collection)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def row_ids(scenario: Mapping[str, Any], collection: str) -> list[str]:
    id_field = _id_field(collection)
    return [str(row[id_field]) for row in rows(scenario, collection) if id_field in row]


def find_row(scenario: Mapping[str, Any], collection: str, item_id: str) -> Row | None:
    id_field = _id_field(collection)
    for row in rows(scenario, collection):
        if row.get(id_field) == item_id:
            return deepcopy(row)
    return None


def set_fields(scenario: Mapping[str, Any], **fields: Any) -> Scenario:
    """Update top-level fields; ``None`` removes an optional field."""
    updated = deepcopy(dict(scenario))
    for key, value in fields.items():
        if key in COLLECTION_ID_FIELDS:
            raise ScenarioEditError(f"Edit {key} through its own functions.")
        if key == "scenario_id" and not is_valid_id(str(value)):
            raise ScenarioEditError(f"{value!r} is not a valid scenario ID.")
        if value is None:
            updated.pop(key, None)
        else:
            updated[key] = deepcopy(value)
    return updated


def upsert_row(scenario: Mapping[str, Any], collection: str, row: Mapping[str, Any]) -> Scenario:
    """Insert a row, or replace the row with the same ID in place.

    For locations, a changed address clears the derived geocoding fields, whether or not
    the new row still carries them.
    """
    id_field = _id_field(collection)
    item_id = row.get(id_field)
    if not isinstance(item_id, str) or not is_valid_id(item_id):
        raise ScenarioEditError(f"{id_field} {item_id!r} is not a valid ID.")
    new_row = deepcopy(dict(row))
    updated = deepcopy(dict(scenario))
    current = rows(updated, collection)
    for index, existing in enumerate(current):
        if existing.get(id_field) == item_id:
            if collection == "locations" and _address_changed(existing, new_row):
                new_row = clear_derived_location_fields(new_row)
            current[index] = new_row
            break
    else:
        current.append(new_row)
    updated[collection] = current
    return updated


def upsert_location(scenario: Mapping[str, Any], location: Mapping[str, Any]) -> Scenario:
    return upsert_row(scenario, "locations", location)


def upsert_vehicle(scenario: Mapping[str, Any], vehicle: Mapping[str, Any]) -> Scenario:
    return upsert_row(scenario, "vehicles", vehicle)


def upsert_shift(scenario: Mapping[str, Any], shift: Mapping[str, Any]) -> Scenario:
    return upsert_row(scenario, "vehicle_shifts", shift)


def upsert_task(scenario: Mapping[str, Any], task: Mapping[str, Any]) -> Scenario:
    return upsert_row(scenario, "tasks", task)


def update_location_address(
    scenario: Mapping[str, Any], location_id: str, address: str
) -> Scenario:
    """Change one address; that location's coordinates and match details are cleared."""
    location = find_row(scenario, "locations", location_id)
    if location is None:
        raise ScenarioEditError(f"Location {location_id} does not exist.")
    location["address"] = address
    return upsert_location(scenario, location)


def clear_derived_location_fields(location: Mapping[str, Any]) -> Row:
    return {key: value for key, value in location.items() if key not in DERIVED_LOCATION_FIELDS}


def location_dependants(scenario: Mapping[str, Any], location_id: str) -> tuple[Dependant, ...]:
    dependants: list[Dependant] = []
    if scenario.get("plant_location_id", "PLANT") == location_id:
        dependants.append(Dependant("plant", location_id))
    for task in rows(scenario, "tasks"):
        if location_id in (task.get("origin_location_id"), task.get("destination_location_id")):
            dependants.append(Dependant("task", str(task.get("task_id"))))
    for shift in rows(scenario, "vehicle_shifts"):
        if location_id in (
            shift.get("start_location_id", "PLANT"),
            shift.get("end_location_id", "PLANT"),
        ):
            dependants.append(Dependant("shift", str(shift.get("shift_id"))))
    return tuple(dependants)


def vehicle_dependants(scenario: Mapping[str, Any], vehicle_id: str) -> tuple[Dependant, ...]:
    return tuple(
        Dependant("shift", str(shift.get("shift_id")))
        for shift in rows(scenario, "vehicle_shifts")
        if shift.get("vehicle_id") == vehicle_id
    )


def tag_dependants(scenario: Mapping[str, Any], tag: str) -> tuple[Dependant, ...]:
    wanted = tag.strip().upper()
    return tuple(
        Dependant("task", str(task.get("task_id")))
        for task in rows(scenario, "tasks")
        if wanted in _tags(task.get("required_vehicle_tags"))
    )


def delete_location(
    scenario: Mapping[str, Any], location_id: str, *, delete_dependants: bool = False
) -> Scenario:
    """Delete a location; refused while tasks or shifts use it unless they go too.

    The plant can never be deleted this way: choose another plant first.
    """
    _require(scenario, "locations", location_id)
    dependants = location_dependants(scenario, location_id)
    if any(dependant.kind == "plant" for dependant in dependants) or (
        dependants and not delete_dependants
    ):
        raise ReferencedItemError(f"Location {location_id}", dependants)
    removed_tasks = {d.item_id for d in dependants if d.kind == "task"}
    removed_shifts = {d.item_id for d in dependants if d.kind == "shift"}
    updated = _without(scenario, "locations", {location_id})
    updated = _without(updated, "tasks", removed_tasks)
    return _without(updated, "vehicle_shifts", removed_shifts)


def delete_vehicle(
    scenario: Mapping[str, Any], vehicle_id: str, *, delete_dependants: bool = False
) -> Scenario:
    """Delete a truck; refused while it has shifts unless they go too."""
    _require(scenario, "vehicles", vehicle_id)
    dependants = vehicle_dependants(scenario, vehicle_id)
    if dependants and not delete_dependants:
        raise ReferencedItemError(f"Truck {vehicle_id}", dependants)
    updated = _without(scenario, "vehicles", {vehicle_id})
    return _without(updated, "vehicle_shifts", {d.item_id for d in dependants})


def delete_shift(scenario: Mapping[str, Any], shift_id: str) -> Scenario:
    _require(scenario, "vehicle_shifts", shift_id)
    return _without(scenario, "vehicle_shifts", {shift_id})


def delete_task(scenario: Mapping[str, Any], task_id: str) -> Scenario:
    _require(scenario, "tasks", task_id)
    return _without(scenario, "tasks", {task_id})


def remove_tag(
    scenario: Mapping[str, Any], tag: str, *, remove_from_tasks: bool = False
) -> Scenario:
    """Remove a tag from every truck; refused while tasks require it unless removed there too."""
    wanted = tag.strip().upper()
    dependants = tag_dependants(scenario, wanted)
    if dependants and not remove_from_tasks:
        raise ReferencedItemError(f"Tag {wanted}", dependants)
    updated = deepcopy(dict(scenario))
    for collection, field in (("vehicles", "tags"), ("tasks", "required_vehicle_tags")):
        new_rows = []
        for row in rows(updated, collection):
            if field in row:
                row[field] = sorted(_tags(row[field]) - {wanted})
            new_rows.append(row)
        if collection in updated:
            updated[collection] = new_rows
    return updated


def rename_location_id(scenario: Mapping[str, Any], old_id: str, new_id: str) -> Scenario:
    """Rename a location and every reference to it (tasks, shifts, plant)."""
    updated = _rename_row(scenario, "locations", old_id, new_id)
    if updated.get("plant_location_id", "PLANT") == old_id:
        updated["plant_location_id"] = new_id
    for task in rows(updated, "tasks"):
        for field in ("origin_location_id", "destination_location_id"):
            if task.get(field) == old_id:
                task[field] = new_id
    for shift in rows(updated, "vehicle_shifts"):
        for field in ("start_location_id", "end_location_id"):
            if shift.get(field, "PLANT") == old_id:
                shift[field] = new_id
    return updated


def rename_vehicle_id(scenario: Mapping[str, Any], old_id: str, new_id: str) -> Scenario:
    """Rename a truck and its shifts' references."""
    updated = _rename_row(scenario, "vehicles", old_id, new_id)
    for shift in rows(updated, "vehicle_shifts"):
        if shift.get("vehicle_id") == old_id:
            shift["vehicle_id"] = new_id
    return updated


def rename_shift_id(scenario: Mapping[str, Any], old_id: str, new_id: str) -> Scenario:
    return _rename_row(scenario, "vehicle_shifts", old_id, new_id)


def rename_task_id(scenario: Mapping[str, Any], old_id: str, new_id: str) -> Scenario:
    return _rename_row(scenario, "tasks", old_id, new_id)


def _id_field(collection: str) -> str:
    try:
        return COLLECTION_ID_FIELDS[collection]
    except KeyError:
        raise ScenarioEditError(f"Unknown collection {collection!r}.") from None


def _require(scenario: Mapping[str, Any], collection: str, item_id: str) -> None:
    if find_row(scenario, collection, item_id) is None:
        raise ScenarioEditError(f"{_id_field(collection)} {item_id} does not exist.")


def _without(scenario: Mapping[str, Any], collection: str, item_ids: set[str]) -> Scenario:
    updated = deepcopy(dict(scenario))
    if not item_ids:
        return updated
    id_field = _id_field(collection)
    updated[collection] = [
        row for row in rows(updated, collection) if row.get(id_field) not in item_ids
    ]
    return updated


def _rename_row(scenario: Mapping[str, Any], collection: str, old_id: str, new_id: str) -> Scenario:
    id_field = _id_field(collection)
    _require(scenario, collection, old_id)
    if not is_valid_id(new_id):
        raise ScenarioEditError(f"{new_id!r} is not a valid ID.")
    if new_id != old_id and new_id in row_ids(scenario, collection):
        raise ScenarioEditError(f"{id_field} {new_id} is already used.")
    updated = deepcopy(dict(scenario))
    renamed = rows(updated, collection)
    for row in renamed:
        if row.get(id_field) == old_id:
            row[id_field] = new_id
    updated[collection] = renamed
    for other in COLLECTION_ID_FIELDS:
        if other != collection and other in updated:
            updated[other] = rows(updated, other)
    return updated


def _address_changed(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    return normalize_address(str(old.get("address", ""))) != normalize_address(
        str(new.get("address", ""))
    )


def normalize_address(address: str) -> str:
    """Collapse whitespace and case; the same rule the backend uses."""
    return " ".join(address.strip().split()).casefold()


def _tags(value: Any) -> set[str]:
    if isinstance(value, str):
        value = value.split(",")
    if isinstance(value, list | tuple | set | frozenset):
        return {str(tag).strip().upper() for tag in value if str(tag).strip()}
    return set()
