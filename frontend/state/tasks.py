"""PO tasks: movements, the task form's rules, filters, and spreadsheet import (plan §9.4-9.5).

Pure functions over the canonical scenario. A task's movement fixes one end at the
plant: a pickup ends there, a drop starts there, and a pickup-drop touches neither.
Times are stored as plant-local wall-clock text, which the backend reads in the plant
timezone. Importing applies all rows or none.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any

from frontend.state.fleet import capacity_value, parse_tags
from frontend.state.ids import is_valid_id, suggest_task_id, unique_id
from frontend.state.scenario_state import (
    Row,
    Scenario,
    ScenarioEditError,
    find_row,
    row_ids,
    rows,
    upsert_task,
)
from frontend.state.settings import DEFAULT_TIMEZONE, MAX_SERVICE_MINUTES, extend_period
from frontend.state.timeutil import to_local, wall_clock_text

PICKUP, DROP, PICKUP_DROP = "PICKUP", "DROP", "PICKUP_DROP"
MOVEMENTS: Mapping[str, str] = {
    PICKUP: "Pickup (supplier → plant)",
    DROP: "Drop (plant → customer)",
    PICKUP_DROP: "Pickup-drop (A → B)",
}
MOVEMENT_SHORT: Mapping[str, str] = {PICKUP: "Pickup", DROP: "Drop", PICKUP_DROP: "Pickup-drop"}
PRIORITY_LABELS: Mapping[int, str] = {
    1: "Routine",
    2: "Normal",
    3: "Important",
    4: "High",
    5: "Critical",
}
PRIORITY_HELP = (
    "Priority matters only when not every PO fits. Then the plan leaves out lower-priority "
    "POs first: one Critical PO outweighs up to fifteen Routine ones. Priority never "
    "breaks a deadline, a truck's capacity, or a shift, and a PO that is impossible on "
    "its own stays impossible whatever its priority."
)
DUE_EVENTS: Mapping[str, str] = {
    "DELIVERY_COMPLETE": "Delivery complete",
    "PICKUP_COMPLETE": "Pickup complete",
}
DUE_EVENT_HELP = (
    "Delivery complete: the goods must be delivered, unloading included, by the due "
    "time. Pickup complete: they must be loaded by then; delivery may follow later in "
    "the shift."
)


def plant_id(scenario: Mapping[str, Any]) -> str:
    return str(scenario.get("plant_location_id", "PLANT"))


def location_label(scenario: Mapping[str, Any], location_id: str) -> str:
    location = find_row(scenario, "locations", location_id)
    name = location.get("name") if location else None
    return f"{name} ({location_id})" if name else location_id


def free_end_choices(scenario: Mapping[str, Any]) -> list[str]:
    """Locations a planner picks for the non-plant ends: everything but the plant."""
    plant = plant_id(scenario)
    return [location_id for location_id in row_ids(scenario, "locations") if location_id != plant]


def endpoints(
    scenario: Mapping[str, Any], movement: str, origin: str | None, destination: str | None
) -> tuple[str, str]:
    """The task's two ends with the plant end filled in by its movement."""
    plant = plant_id(scenario)
    if movement == PICKUP:
        origin, destination = origin, plant
    elif movement == DROP:
        origin, destination = plant, destination
    elif movement != PICKUP_DROP:
        raise ScenarioEditError(f"Unknown movement {movement!r}.")
    if not origin:
        raise ScenarioEditError("Choose where the goods are picked up.")
    if not destination:
        raise ScenarioEditError("Choose where the goods are delivered.")
    if movement == PICKUP_DROP and plant in (origin, destination):
        raise ScenarioEditError("A pickup-drop goes between two places other than the plant.")
    if movement == PICKUP and origin == plant:
        raise ScenarioEditError("A pickup goes from a supplier to the plant.")
    if movement == DROP and destination == plant:
        raise ScenarioEditError("A drop goes from the plant to a customer.")
    if origin == destination:
        raise ScenarioEditError("The pickup and delivery locations must differ.")
    known = set(row_ids(scenario, "locations"))
    for location_id in (origin, destination):
        if location_id not in known:
            raise ScenarioEditError(f"Location {location_id} does not exist.")
    return origin, destination


@dataclass(frozen=True, slots=True)
class TaskFields:
    """What the task form collects."""

    po_number: str
    movement: str
    origin: str | None
    destination: str | None
    quantity: float | int | str | Decimal
    ready_day: date
    ready_time: time
    due_day: date
    due_time: time
    due_event: str = "DELIVERY_COMPLETE"
    pickup_service_minutes: int = 0
    delivery_service_minutes: int = 0
    priority: int = 1
    required_vehicle_tags: Sequence[str] = ()
    notes: str = ""


def _task_row(scenario: Mapping[str, Any], task: Row, fields: TaskFields) -> Row:
    po_number = " ".join(fields.po_number.split())
    if not po_number:
        raise ScenarioEditError("Enter the PO number.")
    origin, destination = endpoints(scenario, fields.movement, fields.origin, fields.destination)
    ready = wall_clock_text(fields.ready_day, fields.ready_time)
    due = wall_clock_text(fields.due_day, fields.due_time)
    if datetime.fromisoformat(ready) > datetime.fromisoformat(due):
        raise ScenarioEditError("The ready time must not be after the due time.")
    if fields.due_event not in DUE_EVENTS:
        raise ScenarioEditError(f"Unknown deadline event {fields.due_event!r}.")
    for label, minutes in (
        ("Pickup service minutes", fields.pickup_service_minutes),
        ("Delivery service minutes", fields.delivery_service_minutes),
    ):
        if not 0 <= int(minutes) <= MAX_SERVICE_MINUTES:
            raise ScenarioEditError(f"{label} must be between 0 and {MAX_SERVICE_MINUTES}.")
    if fields.priority not in PRIORITY_LABELS:
        raise ScenarioEditError("Priority must be 1 to 5.")
    try:
        quantity = capacity_value(fields.quantity)
    except ScenarioEditError as exc:
        raise ScenarioEditError(str(exc).replace("Capacity", "Quantity")) from None
    task.update(
        {
            "po_number": po_number,
            "task_type": fields.movement,
            "origin_location_id": origin,
            "destination_location_id": destination,
            "quantity": quantity,
            "ready_at": ready,
            "due_at": due,
            "due_event": fields.due_event,
            "pickup_service_minutes": int(fields.pickup_service_minutes),
            "delivery_service_minutes": int(fields.delivery_service_minutes),
            "priority": int(fields.priority),
        }
    )
    tags = parse_tags(fields.required_vehicle_tags)
    if tags:
        task["required_vehicle_tags"] = tags
    else:
        task.pop("required_vehicle_tags", None)
    notes = fields.notes.strip()
    if notes:
        task["notes"] = notes
    else:
        task.pop("notes", None)
    return task


@dataclass(frozen=True, slots=True)
class TaskEdit:
    scenario: Scenario
    task_id: str
    period_extended: bool


def add_task(
    scenario: Mapping[str, Any], fields: TaskFields, *, task_id: str | None = None
) -> TaskEdit:
    existing = row_ids(scenario, "tasks")
    chosen = (task_id or "").strip() or suggest_task_id(existing)
    if not is_valid_id(chosen):
        raise ScenarioEditError(f"{chosen!r} is not a valid task ID.")
    if chosen in existing:
        raise ScenarioEditError(f"Task ID {chosen} is already used.")
    task = _task_row(scenario, {"task_id": chosen}, fields)
    updated, extended = extend_period(
        upsert_task(scenario, task), [task["ready_at"], task["due_at"]]
    )
    return TaskEdit(updated, chosen, extended)


def edit_task(scenario: Mapping[str, Any], task_id: str, fields: TaskFields) -> TaskEdit:
    task = find_row(scenario, "tasks", task_id)
    if task is None:
        raise ScenarioEditError(f"Task {task_id} does not exist.")
    task = _task_row(scenario, task, fields)
    updated, extended = extend_period(
        upsert_task(scenario, task), [task["ready_at"], task["due_at"]]
    )
    return TaskEdit(updated, task_id, extended)


def duplicate_task(scenario: Mapping[str, Any], task_id: str) -> TaskEdit:
    """Same lane, times, and load with a new ID; the PO number is marked as a copy."""
    task = find_row(scenario, "tasks", task_id)
    if task is None:
        raise ScenarioEditError(f"Task {task_id} does not exist.")
    new_id = suggest_task_id(row_ids(scenario, "tasks"))
    task["task_id"] = new_id
    task["po_number"] = unique_po_copy(scenario, str(task.get("po_number", task_id)))
    return TaskEdit(upsert_task(scenario, task), new_id, False)


def form_fields(scenario: Mapping[str, Any], task: Mapping[str, Any]) -> TaskFields:
    """A stored task as the form shows it, in plant-local time."""
    timezone = str(scenario.get("timezone") or DEFAULT_TIMEZONE)
    ready = _local_or_none(task.get("ready_at"), timezone)
    due = _local_or_none(task.get("due_at"), timezone)
    today = date.today()
    return TaskFields(
        po_number=str(task.get("po_number", "")),
        movement=str(task.get("task_type", PICKUP)),
        origin=str(task["origin_location_id"]) if task.get("origin_location_id") else None,
        destination=(
            str(task["destination_location_id"]) if task.get("destination_location_id") else None
        ),
        quantity=task.get("quantity", 1),
        ready_day=ready.date() if ready else today,
        ready_time=ready.time().replace(tzinfo=None) if ready else time(7, 0),
        due_day=due.date() if due else today,
        due_time=due.time().replace(tzinfo=None) if due else time(17, 0),
        due_event=str(task.get("due_event") or "DELIVERY_COMPLETE"),
        pickup_service_minutes=int(task.get("pickup_service_minutes", 0) or 0),
        delivery_service_minutes=int(task.get("delivery_service_minutes", 0) or 0),
        priority=int(task.get("priority", 1) or 1),
        required_vehicle_tags=parse_tags(task.get("required_vehicle_tags")),
        notes=str(task.get("notes") or ""),
    )


def _local_or_none(value: Any, timezone: str) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), time(0, 0))
        return to_local(text, timezone)
    except ValueError:
        return None


def task_warnings(scenario: Mapping[str, Any], task: Mapping[str, Any]) -> list[str]:
    """Problems the planner should see at once, before any validation round trip."""
    enabled = [vehicle for vehicle in rows(scenario, "vehicles") if vehicle.get("enabled", True)]
    if not enabled:
        return ["There is no enabled truck yet. Add trucks on the Fleet page."]
    wanted = set(parse_tags(task.get("required_vehicle_tags")))
    tagged = [vehicle for vehicle in enabled if wanted <= set(parse_tags(vehicle.get("tags")))]
    if not tagged:
        return [f"No enabled truck has the tags {', '.join(sorted(wanted))}."]
    try:
        quantity = Decimal(str(task.get("quantity")))
        largest = max(Decimal(str(vehicle.get("capacity", 0))) for vehicle in tagged)
    except ArithmeticError:
        return []
    if quantity > largest:
        which = "with these tags " if wanted else ""
        return [f"No enabled truck {which}can carry {quantity}; the largest holds {largest}."]
    return []


def filter_tasks(
    scenario: Mapping[str, Any],
    *,
    movements: Iterable[str] = (),
    location_id: str | None = None,
    priorities: Iterable[int] = (),
) -> list[Row]:
    wanted_movements = set(movements)
    wanted_priorities = set(priorities)
    result = []
    for task in rows(scenario, "tasks"):
        if wanted_movements and task.get("task_type") not in wanted_movements:
            continue
        if location_id and location_id not in (
            task.get("origin_location_id"),
            task.get("destination_location_id"),
        ):
            continue
        if wanted_priorities and int(task.get("priority", 1) or 1) not in wanted_priorities:
            continue
        result.append(task)
    return result


def task_table_rows(
    scenario: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]], unit: str
) -> list[dict[str, Any]]:
    timezone = str(scenario.get("timezone") or DEFAULT_TIMEZONE)
    result = []
    for task in tasks:
        priority = int(task.get("priority", 1) or 1)
        result.append(
            {
                "PO": task.get("po_number"),
                "Movement": MOVEMENT_SHORT.get(str(task.get("task_type")), task.get("task_type")),
                "From": _name(scenario, task.get("origin_location_id")),
                "To": _name(scenario, task.get("destination_location_id")),
                "Quantity": f"{task.get('quantity')} {unit}",
                "Ready": _when(task.get("ready_at"), timezone),
                "Due": _when(task.get("due_at"), timezone),
                "Deadline": DUE_EVENTS.get(str(task.get("due_event")), "Delivery complete"),
                "Priority": f"{priority} {PRIORITY_LABELS.get(priority, '')}".strip(),
                "Tags": ", ".join(parse_tags(task.get("required_vehicle_tags"))) or "—",
                "Notes": task.get("notes") or "",
                "ID": task.get("task_id"),
            }
        )
    return result


def _name(scenario: Mapping[str, Any], location_id: Any) -> str:
    if not location_id:
        return "—"
    location = find_row(scenario, "locations", str(location_id))
    return str(location.get("name") or location_id) if location else str(location_id)


def _when(value: Any, timezone: str) -> str:
    moment = _local_or_none(value, timezone)
    if moment is None:
        return str(value or "—")
    if len(str(value)) == 10:
        return moment.strftime("%a %Y-%m-%d") + " (shift boundary)"
    return moment.strftime("%a %Y-%m-%d %H:%M")


# --- import -------------------------------------------------------------------------


class ImportMode(StrEnum):
    APPEND = "append"
    UPDATE = "update"
    REPLACE = "replace"


IMPORT_MODE_LABELS: Mapping[ImportMode, str] = {
    ImportMode.APPEND: "Append as new tasks",
    ImportMode.UPDATE: "Update tasks with matching IDs, add the rest",
    ImportMode.REPLACE: "Replace all tasks",
}
IMPORTED_TASK_FIELDS = (
    "task_id",
    "po_number",
    "task_type",
    "origin_location_id",
    "destination_location_id",
    "quantity",
    "ready_at",
    "due_at",
    "due_event",
    "pickup_service_minutes",
    "delivery_service_minutes",
    "priority",
    "required_vehicle_tags",
    "notes",
)


@dataclass(frozen=True, slots=True)
class TaskImportOutcome:
    scenario: Scenario
    added: tuple[str, ...]
    updated: tuple[str, ...]
    removed: tuple[str, ...]
    period_extended: bool


def apply_imported_tasks(
    scenario: Mapping[str, Any],
    imported: Sequence[Mapping[str, Any]],
    mode: ImportMode,
) -> TaskImportOutcome:
    """Apply checked import rows all-or-nothing; any problem raises and changes nothing.

    Append adds every row as a new task and refuses an ID that already exists. Update
    replaces tasks whose ID matches and adds the rest. Replace makes the imported rows
    the whole task list. Rows without an ID get the next ``TASK-NNNN``.
    """
    if not imported:
        raise ScenarioEditError("There are no rows to import.")
    current = rows(scenario, "tasks")
    current_ids = [str(task.get("task_id")) for task in current]
    base: list[Row] = [] if mode is ImportMode.REPLACE else [dict(task) for task in current]
    position = {str(task.get("task_id")): index for index, task in enumerate(base)}
    taken = [str(task.get("task_id")) for task in base]
    known_locations = set(row_ids(scenario, "locations"))
    added: list[str] = []
    updated: list[str] = []
    seen: set[str] = set()
    times: list[str] = []
    for row in imported:
        label = f"Row {row.get('row_number')}" if row.get("row_number") else "A row"
        task = _imported_task(row)
        task_id = str(task.get("task_id") or "")
        if task_id and task_id in seen:
            raise ScenarioEditError(f"{label} repeats task ID {task_id}.")
        if not task_id:
            task_id = suggest_task_id([*taken, *seen])
            task["task_id"] = task_id
        elif not is_valid_id(task_id):
            raise ScenarioEditError(f"{label}: {task_id!r} is not a valid task ID.")
        for field in ("origin_location_id", "destination_location_id"):
            if task.get(field) not in known_locations:
                raise ScenarioEditError(f"{label}: location {task.get(field)} does not exist.")
        if task_id in position:
            if mode is ImportMode.APPEND:
                raise ScenarioEditError(
                    f"{label}: task {task_id} already exists. Choose 'Update tasks with "
                    "matching IDs', or clear the ID to add it as a new task."
                )
            base[position[task_id]] = task
            updated.append(task_id)
        else:
            position[task_id] = len(base)
            base.append(task)
            added.append(task_id)
        seen.add(task_id)
        taken.append(task_id)
        times.extend(str(task[key]) for key in ("ready_at", "due_at"))
    result = dict(scenario)
    result["tasks"] = base
    removed = (
        tuple(task_id for task_id in current_ids if task_id not in seen)
        if mode is ImportMode.REPLACE
        else ()
    )
    result, extended = extend_period(result, times)
    return TaskImportOutcome(result, tuple(added), tuple(updated), removed, extended)


def _imported_task(row: Mapping[str, Any]) -> Row:
    task: Row = {field: row[field] for field in IMPORTED_TASK_FIELDS if field in row}
    if not task.get("required_vehicle_tags"):
        task.pop("required_vehicle_tags", None)
    else:
        task["required_vehicle_tags"] = parse_tags(task["required_vehicle_tags"])
    if not task.get("notes"):
        task.pop("notes", None)
    if not task.get("task_id"):
        task.pop("task_id", None)
    return task


def unique_po_copy(scenario: Mapping[str, Any], po_number: str) -> str:
    """A PO number not used yet, for copies: ``PO-1 (copy)``, ``PO-1 (copy)-2``…"""
    used = [str(task.get("po_number")) for task in rows(scenario, "tasks")]
    return unique_id(f"{po_number} (copy)", used)
