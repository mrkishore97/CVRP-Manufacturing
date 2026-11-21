"""Fleet state: trucks, shifts, and the shift generator (plan §9.3, V1.1-M4).

Plan check: shift generator gives unique IDs, flags overlaps, skips existing shifts,
and handles several days with a weekday selection.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

import pytest

from frontend.state.fleet import (
    GeneratedStatus,
    add_shift,
    add_vehicle,
    apply_generated_shifts,
    duplicate_shift,
    duplicate_vehicle,
    edit_shift,
    edit_vehicle,
    fleet_tags,
    generate_shifts,
    overlapping_shift_ids,
    shift_table_rows,
    shift_times,
    vehicle_table_rows,
)
from frontend.state.scenario_state import ScenarioEditError, find_row, new_scenario, rows

MONDAY = date(2026, 12, 7)


def _scenario() -> dict[str, Any]:
    scenario = new_scenario(scenario_id="FLEET", start_day=MONDAY, days=1)
    scenario["locations"] = [
        {"location_id": "PLANT", "name": "Plant", "address": "1 Plant Rd"},
        {"location_id": "HUB", "name": "Hub", "address": "2 Hub Rd"},
    ]
    return scenario


def _with_trucks(*names: str) -> dict[str, Any]:
    scenario = _scenario()
    for name in names:
        scenario, _ = add_vehicle(scenario, name=name, capacity=12)
    return scenario


# --- trucks -------------------------------------------------------------------------


def test_add_truck_suggests_an_id_and_stores_backend_units() -> None:
    scenario, vehicle_id = add_vehicle(
        _scenario(),
        name="Reefer 1",
        capacity="8.250",
        tags="refrigerated, Std",
        max_duration_seconds=9 * 3_600,
        max_distance_km=250.5,
    )

    assert vehicle_id == "REEFER-1"
    assert find_row(scenario, "vehicles", "REEFER-1") == {
        "vehicle_id": "REEFER-1",
        "name": "Reefer 1",
        "capacity": 8.25,
        "enabled": True,
        "tags": ["REFRIGERATED", "STD"],
        "maximum_route_duration_seconds": 32_400,
        "maximum_route_distance_meters": 250_500,
    }
    assert fleet_tags(scenario) == ["REFRIGERATED", "STD"]


@pytest.mark.parametrize(
    ("capacity", "message"),
    [(0, "more than zero"), (-3, "more than zero"), ("1.2345", "three decimal"), ("x", "number")],
)
def test_capacity_rules_match_the_backend(capacity: Any, message: str) -> None:
    with pytest.raises(ScenarioEditError, match=message):
        add_vehicle(_scenario(), name="T", capacity=capacity)


def test_edit_truck_clears_limits_and_tags_when_emptied() -> None:
    scenario, vehicle_id = add_vehicle(
        _scenario(), name="T", capacity=5, tags="A", max_duration_seconds=3_600, max_distance_km=9
    )

    edited = edit_vehicle(
        scenario,
        vehicle_id,
        name="Truck T",
        capacity=6,
        enabled=False,
        tags="",
        max_duration_seconds=None,
        max_distance_km=None,
    )

    assert find_row(edited, "vehicles", vehicle_id) == {
        "vehicle_id": vehicle_id,
        "name": "Truck T",
        "capacity": 6,
        "enabled": False,
    }


def test_duplicate_truck_gets_a_new_id_and_no_shifts() -> None:
    scenario = _with_trucks("Truck 1")
    scenario = add_shift(
        scenario, vehicle_id="TRUCK-1", day=MONDAY, start=time(7), end=time(17)
    ).scenario

    copied, copy_id = duplicate_vehicle(scenario, "TRUCK-1")

    assert copy_id == "TRUCK-1-2"
    assert find_row(copied, "vehicles", copy_id)["name"] == "Truck 1 (copy)"  # type: ignore[index]
    assert len(rows(copied, "vehicle_shifts")) == 1
    table = vehicle_table_rows(copied, "pallets")
    assert [row["Shifts"] for row in table] == [1, 0]
    assert table[0]["Capacity"] == "12 pallets"


# --- shifts -------------------------------------------------------------------------


def test_shift_defaults_to_the_plant_and_keeps_the_json_short() -> None:
    edit = add_shift(
        _with_trucks("Truck 1"), vehicle_id="TRUCK-1", day=MONDAY, start=time(7), end=time(17)
    )

    assert edit.shift_id == "TRUCK-1-20261207"
    assert find_row(edit.scenario, "vehicle_shifts", edit.shift_id) == {
        "shift_id": "TRUCK-1-20261207",
        "vehicle_id": "TRUCK-1",
        "start": "2026-12-07T07:00:00",
        "end": "2026-12-07T17:00:00",
    }
    assert not edit.period_extended


def test_an_end_at_or_before_the_start_is_the_next_day() -> None:
    assert shift_times(MONDAY, time(22), time(6)) == (
        "2026-12-07T22:00:00",
        "2026-12-08T06:00:00",
    )


def test_a_shift_outside_the_period_extends_it_to_whole_days() -> None:
    edit = add_shift(
        _with_trucks("Truck 1"),
        vehicle_id="TRUCK-1",
        day=MONDAY,
        start=time(22),
        end=time(6),
        end_location_id="HUB",
        max_duration_seconds=7_200,
    )

    assert edit.period_extended
    assert edit.scenario["planning_horizon"] == {
        "start": "2026-12-07T00:00:00",
        "end": "2026-12-09T00:00:00",
    }
    shift = find_row(edit.scenario, "vehicle_shifts", edit.shift_id)
    assert shift is not None
    assert shift["end_location_id"] == "HUB"
    assert shift["maximum_route_duration_seconds"] == 7_200


def test_edit_shift_and_copy_to_the_next_day() -> None:
    scenario = add_shift(
        _with_trucks("Truck 1"), vehicle_id="TRUCK-1", day=MONDAY, start=time(7), end=time(17)
    ).scenario
    edited = edit_shift(
        scenario,
        "TRUCK-1-20261207",
        vehicle_id="TRUCK-1",
        day=MONDAY,
        start=time(8),
        end=time(16),
        start_location_id="PLANT",
        end_location_id="PLANT",
        max_duration_seconds=None,
    ).scenario
    copy = duplicate_shift(edited, "TRUCK-1-20261207")

    assert copy.shift_id == "TRUCK-1-20261208"
    assert copy.period_extended
    shift = find_row(copy.scenario, "vehicle_shifts", copy.shift_id)
    assert shift is not None
    assert (shift["start"], shift["end"]) == ("2026-12-08T08:00:00", "2026-12-08T16:00:00")


def test_unknown_truck_or_location_is_refused() -> None:
    scenario = _with_trucks("Truck 1")
    with pytest.raises(ScenarioEditError, match="Truck"):
        add_shift(scenario, vehicle_id="NOPE", day=MONDAY, start=time(7), end=time(17))
    with pytest.raises(ScenarioEditError, match="location"):
        add_shift(
            scenario,
            vehicle_id="TRUCK-1",
            day=MONDAY,
            start=time(7),
            end=time(17),
            end_location_id="NOWHERE",
        )


def test_overlapping_shifts_are_flagged_in_the_table() -> None:
    scenario = add_shift(
        _with_trucks("Truck 1"), vehicle_id="TRUCK-1", day=MONDAY, start=time(7), end=time(17)
    ).scenario
    scenario = add_shift(
        scenario, vehicle_id="TRUCK-1", day=MONDAY, start=time(16), end=time(20), shift_id="LATE"
    ).scenario

    assert overlapping_shift_ids(scenario) == {"LATE": "TRUCK-1-20261207"}
    checks = {row["ID"]: row["Check"] for row in shift_table_rows(scenario)}
    assert checks == {"TRUCK-1-20261207": "", "LATE": "Overlaps TRUCK-1-20261207"}


# --- generator ----------------------------------------------------------------------


def test_generator_covers_several_days_on_the_chosen_weekdays_with_unique_ids() -> None:
    scenario = _with_trucks("Truck 1", "Truck 2", "Truck 3")
    generated = generate_shifts(
        scenario,
        vehicle_ids=["TRUCK-1", "TRUCK-2", "TRUCK-3"],
        first_day=MONDAY,
        last_day=date(2026, 12, 20),  # two weeks
        weekdays=range(5),
        start=time(7),
        end=time(17),
    )

    assert len(generated) == 30
    assert {item.status for item in generated} == {GeneratedStatus.NEW}
    ids = [item.shift_id for item in generated]
    assert len(set(ids)) == 30
    assert "TRUCK-2-20261218" in ids
    assert all(item.day.weekday() < 5 for item in generated)


def test_generator_skips_existing_shifts_and_flags_overlaps() -> None:
    scenario = _with_trucks("Truck 1", "Truck 2")
    scenario = add_shift(
        scenario, vehicle_id="TRUCK-1", day=MONDAY, start=time(7), end=time(17)
    ).scenario
    scenario = add_shift(
        scenario,
        vehicle_id="TRUCK-2",
        day=date(2026, 12, 8),
        start=time(15),
        end=time(23),
        shift_id="TRUCK-2-EVENING",
    ).scenario
    # A shift using the ID the generator would suggest for Truck 2 on Monday.
    scenario = add_shift(
        scenario,
        vehicle_id="TRUCK-2",
        day=date(2026, 12, 9),
        start=time(18),
        end=time(22),
        shift_id="TRUCK-2-20261207",
    ).scenario

    generated = generate_shifts(
        scenario,
        vehicle_ids=["TRUCK-1", "TRUCK-2"],
        first_day=MONDAY,
        last_day=date(2026, 12, 8),
        weekdays={0, 1},
        start=time(7),
        end=time(17),
    )

    statuses = {(item.vehicle_id, item.day.day): item for item in generated}
    assert statuses["TRUCK-1", 7].status is GeneratedStatus.EXISTS
    assert statuses["TRUCK-1", 7].note == "TRUCK-1-20261207"
    assert statuses["TRUCK-2", 8].status is GeneratedStatus.OVERLAPS
    assert statuses["TRUCK-2", 8].note == "TRUCK-2-EVENING"
    assert statuses["TRUCK-2", 7].shift_id == "TRUCK-2-20261207-2"
    assert statuses["TRUCK-1", 8].shift_id == "TRUCK-1-20261208"

    outcome = apply_generated_shifts(scenario, generated, end_location_id="HUB")

    assert set(outcome.added) == {"TRUCK-2-20261207-2", "TRUCK-1-20261208"}
    assert outcome.skipped == 2
    assert overlapping_shift_ids(outcome.scenario) == {}
    added = find_row(outcome.scenario, "vehicle_shifts", "TRUCK-1-20261208")
    assert added is not None and added["end_location_id"] == "HUB"
    # Running the generator again finds everything already there.
    again = generate_shifts(
        outcome.scenario,
        vehicle_ids=["TRUCK-1", "TRUCK-2"],
        first_day=MONDAY,
        last_day=date(2026, 12, 8),
        weekdays={0, 1},
        start=time(7),
        end=time(17),
    )
    assert GeneratedStatus.NEW not in {item.status for item in again}


def test_generated_shifts_outside_the_period_extend_it() -> None:
    scenario = _with_trucks("Truck 1")
    generated = generate_shifts(
        scenario,
        vehicle_ids=["TRUCK-1"],
        first_day=MONDAY,
        last_day=date(2026, 12, 9),
        weekdays=range(7),
        start=time(7),
        end=time(15),
    )

    outcome = apply_generated_shifts(scenario, generated)

    assert outcome.period_extended
    assert outcome.scenario["planning_horizon"]["end"] == "2026-12-10T00:00:00"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"weekdays": ()}, "weekday"),
        ({"vehicle_ids": []}, "truck"),
        ({"last_day": date(2026, 12, 1)}, "last day"),
    ],
)
def test_generator_refuses_empty_choices(kwargs: dict[str, Any], message: str) -> None:
    arguments: dict[str, Any] = {
        "vehicle_ids": ["TRUCK-1"],
        "first_day": MONDAY,
        "last_day": MONDAY,
        "weekdays": range(7),
        "start": time(7),
        "end": time(17),
        **kwargs,
    }
    with pytest.raises(ScenarioEditError, match=message):
        generate_shifts(_with_trucks("Truck 1"), **arguments)
