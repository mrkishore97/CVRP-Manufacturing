"""V1.1-M3 scenario settings: identity, timezone, period, plant, planner defaults."""

from __future__ import annotations

from datetime import date, time
from typing import Any

import pytest

from frontend.state import settings
from frontend.state.readiness import LocationReadiness, readiness_by_location
from frontend.state.scenario_state import ScenarioEditError, find_row, new_scenario
from frontend.tests.scenario_fixtures import NOW, small_scenario


def _empty() -> dict[str, Any]:
    return new_scenario(start_day=date(2026, 12, 7))


def test_setting_the_plant_creates_it_first_then_edits_it_in_place() -> None:
    scenario = _empty()
    scenario["locations"] = [{"location_id": "ACME", "name": "Acme", "address": "1 Acme St"}]

    created = settings.set_plant(scenario, name=" Main  plant ", address="300 City Centre Dr")

    assert created["locations"][0] == {
        "location_id": "PLANT",
        "name": "Main plant",
        "address": "300 City Centre Dr",
    }
    assert created["plant_location_id"] == "PLANT"
    renamed = settings.set_plant(created, name="Plant 1", address="300 City Centre Dr")
    assert [row["location_id"] for row in renamed["locations"]] == ["PLANT", "ACME"]
    assert renamed["locations"][0]["name"] == "Plant 1"
    with pytest.raises(ScenarioEditError):
        settings.set_plant(created, name="", address="x")


def test_changing_the_plant_address_clears_its_resolution() -> None:
    scenario = small_scenario()
    scenario["locations"][0].update(
        {"geocode_status": "RESOLVED", "formatted_address": "100 Plant Rd", "place_id": "p"}
    )

    moved = settings.set_plant(scenario, name="Plant", address="1 New Plant Way")

    plant = find_row(moved, "locations", "PLANT")
    assert plant == {"location_id": "PLANT", "name": "Plant", "address": "1 New Plant Way"}
    assert readiness_by_location(moved, now=NOW)["PLANT"] is LocationReadiness.NOT_RESOLVED


def test_another_location_can_become_the_plant() -> None:
    updated = settings.choose_plant(small_scenario(), "SPARE")

    assert updated["plant_location_id"] == "SPARE"
    with pytest.raises(ScenarioEditError):
        settings.choose_plant(small_scenario(), "NOPE")


def test_fit_period_covers_every_shift_and_task_in_whole_local_days() -> None:
    scenario = small_scenario()
    scenario["tasks"][0]["due_at"] = "2026-06-23T03:30:00-04:00"
    scenario["vehicle_shifts"].append(
        {
            "shift_id": "S2",
            "vehicle_id": "TRUCK-1",
            "start": "2026-06-21T22:00:00Z",  # 18:00 on the 21st in Toronto
            "end": "2026-06-22T01:00:00Z",
        }
    )

    assert settings.fitted_period(scenario) == ("2026-06-21T00:00:00", "2026-06-24T00:00:00")
    fitted = settings.fit_period(scenario)
    assert fitted["planning_horizon"] == {
        "start": "2026-06-21T00:00:00",
        "end": "2026-06-24T00:00:00",
    }


def test_fit_period_reads_date_only_values_and_refuses_when_nothing_fits() -> None:
    scenario = small_scenario()
    scenario["vehicle_shifts"] = []
    scenario["tasks"][0]["ready_at"] = "2026-06-25"
    scenario["tasks"][0]["due_at"] = "2026-06-26"

    assert settings.fitted_period(scenario) == ("2026-06-25T00:00:00", "2026-06-27T00:00:00")
    with pytest.raises(ScenarioEditError):
        settings.fit_period(_empty())
    scenario["tasks"][0]["due_at"] = "not a time"
    assert settings.fitted_period(scenario) is None


def test_the_period_is_stored_as_local_wall_clock_text() -> None:
    updated = settings.set_period(
        small_scenario(),
        start_day=date(2026, 11, 1),
        start_time=time(0, 0),
        end_day=date(2026, 11, 2),
        end_time=time(12, 30),
    )

    assert updated["planning_horizon"] == {
        "start": "2026-11-01T00:00:00",
        "end": "2026-11-02T12:30:00",
    }
    bounds = settings.period_bounds(updated)
    assert bounds is not None
    assert bounds[0].utcoffset() != bounds[1].utcoffset()  # crosses the 1 November DST change
    with pytest.raises(ScenarioEditError):
        settings.set_period(
            small_scenario(),
            start_day=date(2026, 11, 2),
            start_time=time(0, 0),
            end_day=date(2026, 11, 2),
            end_time=time(0, 0),
        )


def test_planner_defaults_fill_gaps_and_are_checked() -> None:
    assert settings.planner_defaults(_empty()) == {
        "pickup_service_minutes": 15,
        "delivery_service_minutes": 15,
        "capacity_unit": "units",
    }
    updated = settings.set_planner_defaults(
        small_scenario(),
        pickup_service_minutes=20,
        delivery_service_minutes=0,
        capacity_unit="  ",
    )
    assert updated["planner_defaults"]["pickup_service_minutes"] == 20
    assert updated["planner_defaults"]["capacity_unit"] == "units"
    assert updated["planner_defaults"]["capacity_unit_label"] == "units"  # unknown keys kept
    with pytest.raises(ScenarioEditError):
        settings.set_planner_defaults(
            small_scenario(),
            pickup_service_minutes=-1,
            delivery_service_minutes=0,
            capacity_unit="kg",
        )


def test_identity_and_timezone_are_checked() -> None:
    updated = settings.set_identity(small_scenario(), name="  Week 50  ", scenario_id="WEEK-50")
    assert (updated["name"], updated["scenario_id"]) == ("Week 50", "WEEK-50")
    assert "name" not in settings.set_identity(updated, name=" ", scenario_id="WEEK-50")
    with pytest.raises(ScenarioEditError):
        settings.set_identity(updated, name="x", scenario_id="week 50")

    assert settings.set_timezone(updated, "Europe/Berlin")["timezone"] == "Europe/Berlin"
    with pytest.raises(ScenarioEditError):
        settings.set_timezone(updated, "Mars/Olympus")


def test_timezone_choices_list_iana_zones_and_keep_the_current_one() -> None:
    zones = settings.timezone_choices("America/Toronto")

    assert "America/Toronto" in zones
    assert "Europe/Berlin" in zones
    assert zones == sorted(zones)
    assert settings.timezone_choices("Legacy/Zone")[0] == "Legacy/Zone"
