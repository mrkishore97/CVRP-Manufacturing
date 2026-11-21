"""Task state: movements, the form's rules, filters, and import apply (V1.1-M4).

Plan checks: movement selection fills and locks the plant end; import appends,
updates, or replaces, all-or-nothing on failure.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

import pytest

from frontend.state.fleet import add_vehicle
from frontend.state.scenario_state import ScenarioEditError, find_row, new_scenario, rows
from frontend.state.tasks import (
    DROP,
    PICKUP,
    PICKUP_DROP,
    ImportMode,
    TaskFields,
    add_task,
    apply_imported_tasks,
    duplicate_task,
    edit_task,
    endpoints,
    filter_tasks,
    form_fields,
    task_table_rows,
    task_warnings,
)

MONDAY = date(2026, 12, 7)


def _scenario() -> dict[str, Any]:
    scenario = new_scenario(scenario_id="TASKS", start_day=MONDAY, days=1)
    scenario["locations"] = [
        {"location_id": "PLANT", "name": "Plant", "address": "1 Plant Rd"},
        {"location_id": "ACME", "name": "Acme Steel", "address": "2 Acme Rd"},
        {"location_id": "BOLT", "name": "Bolt Customer", "address": "3 Bolt Rd"},
    ]
    scenario, _ = add_vehicle(scenario, name="Reefer", capacity=8, tags="REFRIGERATED")
    scenario, _ = add_vehicle(scenario, name="Standard", capacity=12)
    return scenario


def _fields(movement: str = PICKUP, **overrides: Any) -> TaskFields:
    values: dict[str, Any] = {
        "po_number": "PO-1",
        "movement": movement,
        "origin": "ACME",
        "destination": "BOLT",
        "quantity": 4,
        "ready_day": MONDAY,
        "ready_time": time(8),
        "due_day": MONDAY,
        "due_time": time(14),
        "pickup_service_minutes": 15,
        "delivery_service_minutes": 10,
    }
    values.update(overrides)
    return TaskFields(**values)


@pytest.mark.parametrize(
    ("movement", "expected"),
    [(PICKUP, ("ACME", "PLANT")), (DROP, ("PLANT", "BOLT")), (PICKUP_DROP, ("ACME", "BOLT"))],
)
def test_the_movement_fills_the_plant_end(movement: str, expected: tuple[str, str]) -> None:
    assert endpoints(_scenario(), movement, "ACME", "BOLT") == expected


@pytest.mark.parametrize(
    ("movement", "origin", "destination", "message"),
    [
        (PICKUP, "PLANT", None, "supplier to the plant"),
        (DROP, None, "PLANT", "plant to a customer"),
        (PICKUP_DROP, "PLANT", "BOLT", "other than the plant"),
        (PICKUP_DROP, "ACME", "ACME", "must differ"),
        (PICKUP_DROP, "ACME", None, "delivered"),
        (PICKUP, "NOWHERE", None, "does not exist"),
    ],
)
def test_movement_rules_agree_with_the_backend(
    movement: str, origin: str | None, destination: str | None, message: str
) -> None:
    with pytest.raises(ScenarioEditError, match=message):
        endpoints(_scenario(), movement, origin, destination)


def test_all_three_movements_are_stored_in_the_planning_shape() -> None:
    scenario = _scenario()
    pickup = add_task(scenario, _fields(PICKUP, priority=5, required_vehicle_tags=["refrigerated"]))
    drop = add_task(pickup.scenario, _fields(DROP, po_number="PO-2", notes="  rear door "))
    pair = add_task(
        drop.scenario, _fields(PICKUP_DROP, po_number="PO-3", due_event="PICKUP_COMPLETE")
    )

    assert [pickup.task_id, drop.task_id, pair.task_id] == ["TASK-0001", "TASK-0002", "TASK-0003"]
    assert find_row(pair.scenario, "tasks", "TASK-0001") == {
        "task_id": "TASK-0001",
        "po_number": "PO-1",
        "task_type": "PICKUP",
        "origin_location_id": "ACME",
        "destination_location_id": "PLANT",
        "quantity": 4,
        "ready_at": "2026-12-07T08:00:00",
        "due_at": "2026-12-07T14:00:00",
        "due_event": "DELIVERY_COMPLETE",
        "pickup_service_minutes": 15,
        "delivery_service_minutes": 10,
        "priority": 5,
        "required_vehicle_tags": ["REFRIGERATED"],
    }
    assert find_row(pair.scenario, "tasks", "TASK-0002")["notes"] == "rear door"  # type: ignore[index]
    assert find_row(pair.scenario, "tasks", "TASK-0003")["due_event"] == "PICKUP_COMPLETE"  # type: ignore[index]


def test_form_fields_round_trip_a_stored_task() -> None:
    scenario = add_task(_scenario(), _fields(DROP, quantity="2.5", priority=3)).scenario
    task = find_row(scenario, "tasks", "TASK-0001")
    assert task is not None

    fields = form_fields(scenario, task)
    edited = edit_task(scenario, "TASK-0001", fields).scenario

    assert find_row(edited, "tasks", "TASK-0001") == task


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"po_number": "  "}, "PO number"),
        ({"due_time": time(7)}, "ready time"),
        ({"quantity": 0}, "Quantity"),
        ({"priority": 6}, "Priority"),
        ({"pickup_service_minutes": 2_000}, "Pickup service"),
    ],
)
def test_form_rules(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ScenarioEditError, match=message):
        add_task(_scenario(), _fields(**overrides))


def test_a_task_outside_the_period_extends_it() -> None:
    edit = add_task(_scenario(), _fields(due_day=date(2026, 12, 8)))

    assert edit.period_extended
    assert edit.scenario["planning_horizon"]["end"] == "2026-12-09T00:00:00"


def test_duplicate_keeps_the_lane_with_a_new_id_and_a_marked_po() -> None:
    scenario = add_task(_scenario(), _fields()).scenario

    first = duplicate_task(scenario, "TASK-0001")
    second = duplicate_task(first.scenario, "TASK-0001")

    copy = find_row(second.scenario, "tasks", "TASK-0003")
    assert copy is not None
    assert copy["origin_location_id"] == "ACME"
    pos = [task["po_number"] for task in rows(second.scenario, "tasks")]
    assert len(set(pos)) == 3
    assert pos[1] == "PO-1 (copy)"


def test_immediate_warnings_for_tags_and_quantity() -> None:
    scenario = _scenario()

    assert task_warnings(scenario, {"quantity": 4, "required_vehicle_tags": ["HAZMAT"]}) == [
        "No enabled truck has the tags HAZMAT."
    ]
    assert task_warnings(scenario, {"quantity": 10, "required_vehicle_tags": ["REFRIGERATED"]}) == [
        "No enabled truck with these tags can carry 10; the largest holds 8."
    ]
    assert task_warnings(scenario, {"quantity": 20}) == [
        "No enabled truck can carry 20; the largest holds 12."
    ]
    assert task_warnings(scenario, {"quantity": 12}) == []


def test_filters_by_movement_location_and_priority() -> None:
    scenario = _scenario()
    scenario = add_task(scenario, _fields(PICKUP, priority=1)).scenario
    scenario = add_task(scenario, _fields(DROP, po_number="PO-2", priority=4)).scenario
    scenario = add_task(scenario, _fields(PICKUP_DROP, po_number="PO-3", priority=4)).scenario

    def ids(**kwargs: Any) -> list[str]:
        return [str(task["task_id"]) for task in filter_tasks(scenario, **kwargs)]

    assert ids(movements=[DROP]) == ["TASK-0002"]
    assert ids(location_id="ACME") == ["TASK-0001", "TASK-0003"]
    assert ids(priorities=[4], location_id="BOLT") == ["TASK-0002", "TASK-0003"]
    table = task_table_rows(scenario, filter_tasks(scenario), "pallets")
    assert table[0]["From"] == "Acme Steel"
    assert table[0]["To"] == "Plant"
    assert table[1]["Priority"] == "4 High"
    assert table[0]["Ready"] == "Mon 2026-12-07 08:00"


# --- import -------------------------------------------------------------------------


def _imported(row_number: int, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "row_number": row_number,
        "task_id": None,
        "po_number": f"PO-IMP-{row_number}",
        "task_type": "DROP",
        "origin_location_id": "PLANT",
        "destination_location_id": "BOLT",
        "quantity": 3,
        "ready_at": "2026-12-07T08:00:00",
        "due_at": "2026-12-07T15:00:00",
        "due_event": "DELIVERY_COMPLETE",
        "pickup_service_minutes": 15,
        "delivery_service_minutes": 15,
        "priority": 1,
        "required_vehicle_tags": [],
        "notes": None,
    }
    row.update(overrides)
    return row


def _with_two_tasks() -> dict[str, Any]:
    scenario = add_task(_scenario(), _fields()).scenario
    return add_task(scenario, _fields(DROP, po_number="PO-2")).scenario


def test_append_numbers_new_rows_after_existing_tasks() -> None:
    outcome = apply_imported_tasks(
        _with_two_tasks(), [_imported(2), _imported(3, notes="x")], ImportMode.APPEND
    )

    assert outcome.added == ("TASK-0003", "TASK-0004")
    assert [task["task_id"] for task in rows(outcome.scenario, "tasks")] == [
        "TASK-0001",
        "TASK-0002",
        "TASK-0003",
        "TASK-0004",
    ]
    stored = find_row(outcome.scenario, "tasks", "TASK-0003")
    assert stored is not None
    assert "row_number" not in stored and "notes" not in stored
    assert "required_vehicle_tags" not in stored


def test_update_replaces_matching_ids_in_place_and_adds_the_rest() -> None:
    outcome = apply_imported_tasks(
        _with_two_tasks(),
        [_imported(2, task_id="TASK-0002", quantity=9), _imported(3, task_id="NEW-1")],
        ImportMode.UPDATE,
    )

    assert outcome.updated == ("TASK-0002",)
    assert outcome.added == ("NEW-1",)
    assert [task["task_id"] for task in rows(outcome.scenario, "tasks")] == [
        "TASK-0001",
        "TASK-0002",
        "NEW-1",
    ]
    assert find_row(outcome.scenario, "tasks", "TASK-0002")["quantity"] == 9  # type: ignore[index]


def test_replace_makes_the_imported_rows_the_whole_task_list() -> None:
    outcome = apply_imported_tasks(
        _with_two_tasks(), [_imported(2, task_id="TASK-0002")], ImportMode.REPLACE
    )

    assert [task["task_id"] for task in rows(outcome.scenario, "tasks")] == ["TASK-0002"]
    assert outcome.removed == ("TASK-0001",)


@pytest.mark.parametrize(
    ("mode", "bad_row", "message"),
    [
        (ImportMode.APPEND, _imported(3, task_id="TASK-0001"), "already exists"),
        (ImportMode.UPDATE, _imported(3, destination_location_id="GONE"), "does not exist"),
        (ImportMode.REPLACE, _imported(3, task_id="bad id"), "not a valid task ID"),
        (ImportMode.UPDATE, _imported(3, task_id="T-9"), "repeats"),
    ],
)
def test_a_failing_row_imports_nothing(
    mode: ImportMode, bad_row: dict[str, Any], message: str
) -> None:
    scenario = _with_two_tasks()
    before = [dict(task) for task in rows(scenario, "tasks")]
    imported = [_imported(2, task_id="T-9"), bad_row]

    with pytest.raises(ScenarioEditError, match=message):
        apply_imported_tasks(scenario, imported, mode)

    assert rows(scenario, "tasks") == before


def test_imported_times_outside_the_period_extend_it() -> None:
    outcome = apply_imported_tasks(
        _scenario(),
        [_imported(2, ready_at="2026-12-06T08:00:00", due_at="2026-12-06T12:00:00")],
        ImportMode.APPEND,
    )

    assert outcome.period_extended
    assert outcome.scenario["planning_horizon"]["start"] == "2026-12-06T00:00:00"
