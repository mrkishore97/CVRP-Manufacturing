"""V1.1-M2 scenario state: create, upsert, delete, rename, and address edits."""

from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest

from frontend.state import scenario_state as ss
from frontend.tests.scenario_fixtures import small_scenario


def test_new_scenario_is_empty_with_a_whole_day_period() -> None:
    scenario = ss.new_scenario(
        scenario_id="WEEK-26", name="Week 26", start_day=date(2026, 6, 22), days=5
    )

    assert scenario["planning_horizon"] == {
        "start": "2026-06-22T00:00:00",
        "end": "2026-06-27T00:00:00",
    }
    assert scenario["name"] == "Week 26"
    assert all(scenario[key] == [] for key in ss.COLLECTION_ID_FIELDS)
    assert scenario["plant_location_id"] == "PLANT"


@pytest.mark.parametrize("kwargs", [{"scenario_id": "bad id"}, {"scenario_id": "OK", "days": 0}])
def test_new_scenario_rejects_bad_input(kwargs: dict[str, object]) -> None:
    with pytest.raises(ss.ScenarioEditError):
        ss.new_scenario(**kwargs)  # type: ignore[arg-type]


def test_functions_never_mutate_their_input() -> None:
    original = small_scenario()
    snapshot = deepcopy(original)

    ss.upsert_task(original, {**original["tasks"][0], "quantity": 9})
    ss.update_location_address(original, "SUPPLIER_A", "201 Supplier Avenue")
    ss.rename_location_id(original, "SUPPLIER_A", "ACME")
    ss.delete_location(original, "SPARE")

    assert original == snapshot


def test_upsert_inserts_new_and_replaces_existing_in_place() -> None:
    scenario = small_scenario()
    new_truck = {"vehicle_id": "TRUCK-2", "name": "Truck 2", "capacity": 8}

    added = ss.upsert_vehicle(scenario, new_truck)
    replaced = ss.upsert_vehicle(added, {**scenario["vehicles"][0], "capacity": 14})

    assert ss.row_ids(added, "vehicles") == ["TRUCK-1", "TRUCK-2"]
    assert ss.row_ids(replaced, "vehicles") == ["TRUCK-1", "TRUCK-2"]
    assert ss.find_row(replaced, "vehicles", "TRUCK-1") == {
        **scenario["vehicles"][0],
        "capacity": 14,
    }


def test_upsert_refuses_invalid_ids() -> None:
    with pytest.raises(ss.ScenarioEditError, match="not a valid ID"):
        ss.upsert_task(small_scenario(), {"task_id": "has space"})


def test_address_edit_clears_derived_fields() -> None:
    edited = ss.update_location_address(small_scenario(), "SUPPLIER_A", "250 Supplier Avenue")
    location = ss.find_row(edited, "locations", "SUPPLIER_A")

    assert location == {
        "location_id": "SUPPLIER_A",
        "name": "Supplier A",
        "address": "250 Supplier Avenue",
    }


def test_address_edit_clears_supplied_coordinates_too() -> None:
    edited = ss.update_location_address(small_scenario(), "PLANT", "1 New Plant Way")

    assert "latitude" not in (ss.find_row(edited, "locations", "PLANT") or {})


def test_upsert_with_a_new_address_drops_stale_derived_fields_it_carries() -> None:
    scenario = small_scenario()
    stale_row = {**scenario["locations"][1], "address": "999 Elsewhere Road"}

    edited = ss.upsert_location(scenario, stale_row)

    assert not any(
        field in (ss.find_row(edited, "locations", "SUPPLIER_A") or {})
        for field in ss.DERIVED_LOCATION_FIELDS
    )


def test_spacing_or_case_change_is_not_an_address_change() -> None:
    scenario = small_scenario()
    row = {**scenario["locations"][1], "address": "  200 SUPPLIER avenue,  Vaughan, ON "}

    edited = ss.upsert_location(scenario, row)

    assert (ss.find_row(edited, "locations", "SUPPLIER_A") or {})["latitude"] == 43.82


def test_renaming_a_location_name_keeps_derived_fields() -> None:
    scenario = small_scenario()

    edited = ss.upsert_location(scenario, {**scenario["locations"][1], "name": "Acme Steel"})

    assert (ss.find_row(edited, "locations", "SUPPLIER_A") or {})["latitude"] == 43.82


def test_deleting_a_used_location_is_refused_with_its_dependants() -> None:
    with pytest.raises(ss.ReferencedItemError) as raised:
        ss.delete_location(small_scenario(), "SUPPLIER_A")

    assert raised.value.dependants == (ss.Dependant("task", "TASK-0001"),)
    assert "used by 1 task" in str(raised.value)


def test_deleting_with_dependants_removes_them_too() -> None:
    edited = ss.delete_location(small_scenario(), "SUPPLIER_A", delete_dependants=True)

    assert ss.row_ids(edited, "locations") == ["PLANT", "SPARE"]
    assert ss.row_ids(edited, "tasks") == []


def test_the_plant_can_never_be_deleted() -> None:
    for cascade in (False, True):
        with pytest.raises(
            ss.ReferencedItemError, match="the plant and used by 1 task and 1 shift"
        ):
            ss.delete_location(small_scenario(), "PLANT", delete_dependants=cascade)


def test_deleting_an_unused_location_needs_no_confirmation() -> None:
    assert ss.row_ids(ss.delete_location(small_scenario(), "SPARE"), "locations") == [
        "PLANT",
        "SUPPLIER_A",
    ]


def test_deleting_a_truck_with_shifts_is_refused_unless_they_go_too() -> None:
    with pytest.raises(ss.ReferencedItemError, match="used by 1 shift"):
        ss.delete_vehicle(small_scenario(), "TRUCK-1")

    edited = ss.delete_vehicle(small_scenario(), "TRUCK-1", delete_dependants=True)
    assert ss.row_ids(edited, "vehicles") == []
    assert ss.row_ids(edited, "vehicle_shifts") == []


def test_removing_a_required_tag_is_refused_unless_tasks_drop_it() -> None:
    scenario = small_scenario()
    scenario["vehicles"][0]["tags"] = ["REEFER", "LIFTGATE"]
    scenario["tasks"][0]["required_vehicle_tags"] = ["reefer"]

    with pytest.raises(ss.ReferencedItemError, match="Tag REEFER is used by 1 task"):
        ss.remove_tag(scenario, "reefer")
    edited = ss.remove_tag(scenario, "REEFER", remove_from_tasks=True)

    assert edited["vehicles"][0]["tags"] == ["LIFTGATE"]
    assert edited["tasks"][0]["required_vehicle_tags"] == []
    assert ss.remove_tag(scenario, "LIFTGATE")["vehicles"][0]["tags"] == ["REEFER"]


def test_renaming_a_location_cascades_to_every_reference() -> None:
    scenario = small_scenario()
    scenario["vehicle_shifts"][0]["end_location_id"] = "SUPPLIER_A"

    renamed = ss.rename_location_id(scenario, "SUPPLIER_A", "ACME")
    plant_renamed = ss.rename_location_id(scenario, "PLANT", "MAIN-PLANT")

    assert ss.row_ids(renamed, "locations") == ["PLANT", "ACME", "SPARE"]
    assert renamed["tasks"][0]["origin_location_id"] == "ACME"
    assert renamed["vehicle_shifts"][0]["end_location_id"] == "ACME"
    assert plant_renamed["plant_location_id"] == "MAIN-PLANT"
    assert plant_renamed["tasks"][0]["destination_location_id"] == "MAIN-PLANT"
    assert plant_renamed["vehicle_shifts"][0]["start_location_id"] == "MAIN-PLANT"


def test_renaming_a_truck_cascades_to_its_shifts() -> None:
    renamed = ss.rename_vehicle_id(small_scenario(), "TRUCK-1", "UNIT-7")

    assert renamed["vehicle_shifts"][0]["vehicle_id"] == "UNIT-7"


@pytest.mark.parametrize(("new_id", "message"), [("SPARE", "already used"), ("a b", "valid")])
def test_rename_refuses_duplicates_and_invalid_ids(new_id: str, message: str) -> None:
    with pytest.raises(ss.ScenarioEditError, match=message):
        ss.rename_location_id(small_scenario(), "SUPPLIER_A", new_id)


def test_set_fields_updates_and_removes_top_level_values() -> None:
    edited = ss.set_fields(small_scenario(), name="Renamed", planner_defaults=None)

    assert edited["name"] == "Renamed"
    assert "planner_defaults" not in edited
    with pytest.raises(ss.ScenarioEditError):
        ss.set_fields(small_scenario(), tasks=[])
