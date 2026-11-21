"""V1.1-M4 validation: Review warnings, issue sections, and shift rules (plan §9.6).

New non-blocking warnings: UNKNOWN_FIELD, UNUSED_LOCATION, VEHICLE_WITHOUT_SHIFT,
NO_COMPATIBLE_VEHICLE, TASK_WINDOW_OUTSIDE_SHIFTS. Every issue names its section and,
where there is one, the row's ID, so the app can group issues and link to the row.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from backend.app.domain import validate_planning_payload
from backend.app.domain.results import ValidationIssue, ValidationResult
from backend.tests.fixtures.canonical import planning_payload

V1_0_COMPAT = Path(__file__).resolve().parents[4] / "sample_data" / "v1_0_compat"
V1_1_DIR = Path(__file__).resolve().parents[4] / "sample_data" / "v1_1"


def _fixture(name: str) -> dict[str, Any]:
    with (V1_1_DIR / name).open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def _g() -> dict[str, Any]:
    return _fixture("v11_g_vehicle_tags.json")


def _issues(result: ValidationResult, code: str) -> list[ValidationIssue]:
    return [issue for issue in result.issues if issue.code.value == code]


def test_the_m4_fixtures_validate_without_any_warning() -> None:
    for name in (
        "v11_f_priority_shortage.json",
        "v11_g_vehicle_tags.json",
        "v11_h_route_limits.json",
        "v11_i_multiday_shift_depots.json",
    ):
        result = validate_planning_payload(_fixture(name))
        assert result.valid, name
        assert result.issues == (), (name, result.issues)


@pytest.mark.parametrize("letter", ["a", "c", "d", "e", "f"])
def test_version_1_0_payloads_stay_valid_with_only_warnings_added(letter: str) -> None:
    with (V1_0_COMPAT / f"scenario_{letter}.json").open(encoding="utf-8") as handle:
        payload = json.load(handle)

    result = validate_planning_payload(payload)

    assert result.valid
    assert {issue.severity.value for issue in result.issues} <= {"WARNING"}


def test_unknown_top_level_field_is_a_warning() -> None:
    payload = _g()
    payload["optimisation_options"] = {"objective_mode": "MINIMIZE_TRAVEL"}

    result = validate_planning_payload(payload)

    assert result.valid
    [issue] = _issues(result, "UNKNOWN_FIELD")
    assert issue.field == "optimisation_options"
    assert issue.section is not None and issue.section.value == "scenario"
    assert "spelling" in issue.message


def test_known_planner_keys_are_not_unknown() -> None:
    payload = _g()
    payload["description"] = "free text"
    payload["routing_options"] = {}
    payload["optimization_options"] = {}

    assert _issues(validate_planning_payload(payload), "UNKNOWN_FIELD") == []


def test_unused_location_is_named() -> None:
    payload = _g()
    payload["locations"].append(
        {"location_id": "SPARE", "name": "Spare yard", "address": "9 Spare Rd, Toronto, ON"}
    )

    [issue] = _issues(validate_planning_payload(payload), "UNUSED_LOCATION")

    assert issue.item_id == "SPARE"
    assert issue.section is not None and issue.section.value == "locations"


def test_a_shift_end_location_counts_as_used() -> None:
    payload = _fixture("v11_i_multiday_shift_depots.json")

    assert _issues(validate_planning_payload(payload), "UNUSED_LOCATION") == []


def test_enabled_truck_without_shift_is_a_warning_and_disabled_one_is_not() -> None:
    payload = _g()
    payload["vehicles"].append(
        {"vehicle_id": "SPARE-1", "name": "Spare", "capacity": 5, "enabled": True}
    )
    payload["vehicles"].append(
        {"vehicle_id": "OLD-1", "name": "Old", "capacity": 5, "enabled": False}
    )

    issues = _issues(validate_planning_payload(payload), "VEHICLE_WITHOUT_SHIFT")

    assert [issue.item_id for issue in issues] == ["SPARE-1"]
    assert issues[0].section is not None and issues[0].section.value == "vehicles"


def test_required_tags_no_enabled_truck_has_are_a_warning() -> None:
    payload = _g()
    payload["tasks"][0]["required_vehicle_tags"] = ["HAZMAT"]

    result = validate_planning_payload(payload)

    assert result.valid
    [issue] = _issues(result, "NO_COMPATIBLE_VEHICLE")
    assert issue.task_id == issue.item_id == "TASK-COLD-1"
    assert "HAZMAT" in issue.message


def test_quantity_only_a_smaller_tagged_truck_could_carry_is_a_warning() -> None:
    payload = _g()
    payload["tasks"][0]["quantity"] = 10  # the refrigerated truck holds 8; standard 12

    result = validate_planning_payload(payload)

    assert result.valid
    [issue] = _issues(result, "NO_COMPATIBLE_VEHICLE")
    assert "largest holds 8" in issue.message
    assert _issues(result, "CAPACITY_EXCEEDED") == []


def test_quantity_above_every_truck_stays_the_version_1_0_error() -> None:
    payload = _g()
    payload["tasks"][2]["quantity"] = 50

    result = validate_planning_payload(payload)

    assert not result.valid
    assert [issue.task_id for issue in _issues(result, "CAPACITY_EXCEEDED")] == ["TASK-DRY-1"]
    assert _issues(result, "NO_COMPATIBLE_VEHICLE") == []


def test_task_window_outside_every_compatible_shift_is_a_warning() -> None:
    payload = _g()
    payload["planning_horizon"]["end"] = "2026-12-09T00:00:00"
    cold = payload["tasks"][0]
    cold["ready_at"] = "2026-12-08T08:00:00"
    cold["due_at"] = "2026-12-08T12:00:00"
    # The standard truck works on the 8th, but it lacks the refrigerated tag.
    payload["vehicle_shifts"].append(
        {
            "shift_id": "STD-1-20261208",
            "vehicle_id": "STD-1",
            "start": "2026-12-08T07:00:00",
            "end": "2026-12-08T17:00:00",
        }
    )

    result = validate_planning_payload(payload)

    assert result.valid
    [issue] = _issues(result, "TASK_WINDOW_OUTSIDE_SHIFTS")
    assert issue.item_id == "TASK-COLD-1"


def test_overlapping_shifts_of_one_truck_are_an_error_on_the_later_shift() -> None:
    payload = _g()
    payload["vehicle_shifts"].append(
        {
            "shift_id": "STD-1-LATE",
            "vehicle_id": "STD-1",
            "start": "2026-12-07T16:00:00",
            "end": "2026-12-07T20:00:00",
        }
    )

    result = validate_planning_payload(payload)

    assert not result.valid
    [issue] = _issues(result, "SHIFT_OVERLAP")
    assert issue.item_id == "STD-1-LATE"
    assert issue.section is not None and issue.section.value == "vehicle_shifts"


def test_shift_outside_the_planning_period_names_the_shift() -> None:
    payload = _g()
    payload["vehicle_shifts"][0]["end"] = "2026-12-08T03:00:00"

    result = validate_planning_payload(payload)

    assert not result.valid
    [issue] = _issues(result, "OUTSIDE_PLANNING_HORIZON")
    assert issue.item_id == "REEFER-1-20261207"


def test_row_errors_carry_their_section_and_id() -> None:
    payload = _g()
    payload["vehicles"][1]["capacity"] = -1
    payload["locations"][1]["latitude"] = 95
    bad_task = deepcopy(payload["tasks"][3])
    bad_task["task_id"] = "TASK-BAD"
    bad_task["ready_at"] = "not a time"
    payload["tasks"].append(bad_task)

    result = validate_planning_payload(payload)

    sections = {
        (issue.section.value if issue.section else None, issue.item_id)
        for issue in result.issues
        if issue.severity.value == "ERROR"
    }
    assert ("vehicles", "STD-1") in sections
    assert ("locations", payload["locations"][1]["location_id"]) in sections
    assert ("tasks", "TASK-BAD") in sections


def test_fixture_metadata_keys_are_reported_as_unknown_fields_only() -> None:
    """The canonical fixture files carry test metadata that the planner ignores."""
    result = validate_planning_payload(planning_payload("A"))

    assert result.valid
    assert {issue.code.value for issue in result.issues} <= {"UNUSED_LOCATION", "UNKNOWN_FIELD"}
    assert {issue.field for issue in _issues(result, "UNKNOWN_FIELD")} == {
        "category",
        "expected",
        "fixture_version",
        "locations_ref",
        "matrix_ref",
    }
