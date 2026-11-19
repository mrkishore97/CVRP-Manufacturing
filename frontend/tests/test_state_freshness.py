"""V1.1-M2 freshness: every row of the plan §12 table, plus readiness and workflow gates.

The Version 1.0 invalidation tests (``test_session_models.py``) are migrated here; each
keeps an equivalent test, marked "migrated".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest

from frontend.state import scenario_state as ss
from frontend.state.readiness import (
    LocationReadiness,
    geocode_fingerprint,
    geocode_fingerprint_matches,
    location_readiness,
    workflow_status,
)
from frontend.state.workspace import (
    Workspace,
    edit,
    record_matrix,
    record_validation,
    solve_payload,
    validation_issue_rows,
    validation_payload_fingerprint,
)
from frontend.tests.scenario_fixtures import (
    NOW,
    SUPPLIER_ADDRESS,
    current_workspace,
    small_matrix,
)

Edit = Callable[[dict[str, Any]], dict[str, Any]]


def _apply(change: Edit, workspace: Workspace | None = None) -> Workspace:
    start = workspace or current_workspace()
    return edit(start, change(start.scenario))


def _readiness(workspace: Workspace) -> dict[str, LocationReadiness]:
    return dict(workflow_status(workspace, now=NOW).readiness)


def test_fixture_starts_fully_current() -> None:
    status = workflow_status(current_workspace(), now=NOW)

    assert status.validation_valid
    assert status.matrix_current
    assert status.plan_current
    assert status.can_solve
    assert _readiness(current_workspace()) == {
        "PLANT": LocationReadiness.SUPPLIED,
        "SUPPLIER_A": LocationReadiness.READY,
        "SPARE": LocationReadiness.SUPPLIED,
    }


def _tweak_task_notes(scenario: dict[str, Any]) -> dict[str, Any]:
    return ss.upsert_task(scenario, {**scenario["tasks"][0], "notes": "Use dock 7"})


def _rename_location(scenario: dict[str, Any]) -> dict[str, Any]:
    return ss.upsert_location(scenario, {**scenario["locations"][1], "name": "Acme Steel"})


def _rename_truck(scenario: dict[str, Any]) -> dict[str, Any]:
    return ss.upsert_vehicle(scenario, {**scenario["vehicles"][0], "name": "Big Blue"})


@pytest.mark.parametrize(
    "change",
    [
        lambda s: ss.set_fields(s, name="Week 26 inbound"),
        lambda s: ss.set_fields(s, scenario_id="RENAMED-SCENARIO"),
        _rename_location,
        _rename_truck,
        _tweak_task_notes,
        lambda s: ss.set_fields(s, planner_defaults={"capacity_unit_label": "pallets"}),
    ],
    ids=["scenario name", "scenario ID", "location name", "truck name", "task notes", "defaults"],
)
def test_row_names_ids_notes_defaults_keep_everything(change: Edit) -> None:
    before = current_workspace()
    after = _apply(change, before)
    status = workflow_status(after, now=NOW)

    assert _readiness(after) == _readiness(before)
    assert status.matrix_current
    assert status.plan_current


def test_row_address_edit_unresolves_that_location_and_stales_travel_times_and_plan() -> None:
    after = _apply(lambda s: ss.update_location_address(s, "SUPPLIER_A", "250 Supplier Avenue"))
    status = workflow_status(after, now=NOW)

    assert _readiness(after) == {
        "PLANT": LocationReadiness.SUPPLIED,
        "SUPPLIER_A": LocationReadiness.NOT_RESOLVED,
        "SPARE": LocationReadiness.SUPPLIED,
    }
    assert not status.matrix_current
    assert not status.plan_current
    assert status.stale_plan_hidden


def test_row_adding_a_location_stales_travel_times_and_plan() -> None:
    new_location = {"location_id": "NEW-DOCK", "name": "New dock", "address": "5 Dock Rd"}
    after = _apply(lambda s: ss.upsert_location(s, new_location))
    status = workflow_status(after, now=NOW)

    assert status.readiness["NEW-DOCK"] is LocationReadiness.NOT_RESOLVED
    assert status.readiness["SUPPLIER_A"] is LocationReadiness.READY
    assert not status.matrix_current
    assert not status.plan_current


def test_row_deleting_an_unused_location_slices_travel_times_and_stales_the_plan() -> None:
    after = _apply(lambda s: ss.delete_location(s, "SPARE"))
    status = workflow_status(after, now=NOW)
    matrix = after.derived.matrix

    assert status.matrix_current
    assert not status.plan_current
    assert matrix is not None
    assert matrix["location_ids"] == ["PLANT", "SUPPLIER_A"]
    assert matrix["distance_meters"] == [[0, 28_000], [27_000, 0]]
    assert matrix["duration_seconds"] == [[0, 1_800], [1_700, 0]]


@pytest.mark.parametrize(
    "routing_options",
    [
        {"routing_preference": "TRAFFIC_AWARE"},
        {"routing_preference": "TRAFFIC_UNAWARE", "departure_time": "2026-06-22T07:00:00"},
    ],
    ids=["routing preference", "departure time"],
)
def test_row_routing_options_stale_travel_times_and_plan(routing_options: dict[str, Any]) -> None:
    after = _apply(lambda s: ss.set_fields(s, routing_options=routing_options))
    status = workflow_status(after, now=NOW)

    assert _readiness(after) == _readiness(current_workspace())
    assert not status.matrix_current
    assert not status.plan_current


def _longer_shift(scenario: dict[str, Any]) -> dict[str, Any]:
    return ss.upsert_shift(
        scenario, {**scenario["vehicle_shifts"][0], "end": "2026-06-22T18:00:00"}
    )


def _bigger_truck(scenario: dict[str, Any]) -> dict[str, Any]:
    return ss.upsert_vehicle(scenario, {**scenario["vehicles"][0], "capacity": 20})


def _later_deadline(scenario: dict[str, Any]) -> dict[str, Any]:
    return ss.upsert_task(scenario, {**scenario["tasks"][0], "due_at": "2026-06-22T13:00:00"})


def _longer_period(scenario: dict[str, Any]) -> dict[str, Any]:
    horizon = {**scenario["planning_horizon"], "end": "2026-06-22T19:00:00"}
    return ss.set_fields(scenario, planning_horizon=horizon)


@pytest.mark.parametrize(
    "change",
    [
        _bigger_truck,
        _longer_shift,
        _later_deadline,
        _longer_period,
        lambda s: ss.set_fields(s, timezone="America/Winnipeg"),
        lambda s: ss.set_fields(s, plant_location_id="SPARE"),
    ],
    ids=["truck", "shift", "task", "period", "timezone", "plant choice"],
)
def test_row_fleet_tasks_period_timezone_plant_keep_travel_times_but_stale_the_plan(
    change: Edit,
) -> None:
    after = _apply(change)
    status = workflow_status(after, now=NOW)

    assert _readiness(after) == _readiness(current_workspace())
    assert status.matrix_current
    assert not status.plan_current


def test_row_optimization_options_stale_only_the_plan() -> None:
    after = _apply(lambda s: ss.set_fields(s, optimization_options={"objective": "BALANCED"}))
    status = workflow_status(after, now=NOW)

    assert status.matrix_current
    assert not status.plan_current


def test_row_new_matrix_stales_the_plan() -> None:
    recalculated = small_matrix()
    recalculated["distance_meters"][0][1] = 29_000
    after = record_matrix(current_workspace(), recalculated, origin="calculated")
    status = workflow_status(after, now=NOW)

    assert status.matrix_current
    assert not status.plan_current


def test_row_coordinates_older_than_thirty_days_unresolve_and_stale_everything() -> None:
    later = NOW + timedelta(days=29)
    status = workflow_status(current_workspace(), now=later)

    assert status.readiness["SUPPLIER_A"] is LocationReadiness.EXPIRED
    assert status.readiness["PLANT"] is LocationReadiness.SUPPLIED
    assert not status.matrix_current
    assert not status.plan_current
    assert not status.can_compute_matrix


def test_renaming_a_location_id_keeps_travel_times_current() -> None:
    start = current_workspace()
    renamed = ss.rename_location_id(start.scenario, "SPARE", "SPARE-DOCK")
    after = edit(start, renamed, renamed_locations={"SPARE": "SPARE-DOCK"})
    status = workflow_status(after, now=NOW)

    assert status.matrix_current
    assert after.derived.matrix is not None
    assert after.derived.matrix["location_ids"] == ["PLANT", "SUPPLIER_A", "SPARE-DOCK"]
    assert not status.plan_current


def test_renaming_a_location_id_without_telling_edit_stales_travel_times() -> None:
    start = current_workspace()
    after = edit(start, ss.rename_location_id(start.scenario, "SPARE", "SPARE-DOCK"))

    assert not workflow_status(after, now=NOW).matrix_current


def test_validation_goes_stale_on_any_edit() -> None:
    after = _apply(lambda s: ss.set_fields(s, name="Changed"))
    status = workflow_status(after, now=NOW)

    assert not status.validation_current
    assert not status.can_solve


# Migrated from test_session_models.py ------------------------------------------------


def test_migrated_editing_location_invalidates_validation_matrix_and_plan() -> None:
    after = _apply(lambda s: ss.update_location_address(s, "SUPPLIER_A", "201 Supplier Ave"))
    status = workflow_status(after, now=NOW)

    assert not status.validation_current
    assert not status.matrix_current
    assert not status.plan_current
    assert status.stale_plan_hidden
    assert not status.can_solve


def test_migrated_editing_deadline_invalidates_plan_but_not_matrix() -> None:
    after = _apply(_later_deadline)
    status = workflow_status(after, now=NOW)

    assert not status.validation_current
    assert status.matrix_current
    assert not status.plan_current
    assert status.stale_plan_hidden


def test_migrated_solve_requires_current_validation_and_matrix() -> None:
    start = current_workspace()
    unvalidated = Workspace(scenario=start.scenario)
    assert not workflow_status(unvalidated, now=NOW).can_compute_matrix
    assert not workflow_status(unvalidated, now=NOW).can_solve

    validated = record_validation(
        unvalidated,
        payload_fingerprint=validation_payload_fingerprint(unvalidated),
        validation={"valid": True, "issues": []},
        request_id=None,
    )
    assert workflow_status(validated, now=NOW).can_compute_matrix
    assert not workflow_status(validated, now=NOW).can_solve

    matrix_ready = record_matrix(validated, small_matrix(), origin="calculated")
    assert workflow_status(matrix_ready, now=NOW).can_solve


def test_invalid_validation_blocks_calculation_and_solving() -> None:
    start = current_workspace()
    invalid = record_validation(
        start,
        payload_fingerprint=validation_payload_fingerprint(start),
        validation={
            "valid": False,
            "issues": [{"severity": "ERROR", "code": "CAPACITY_EXCEEDED", "message": "x"}],
        },
        request_id=None,
    )
    status = workflow_status(invalid, now=NOW)

    assert status.validation_current and not status.validation_valid
    assert status.error_count == 1
    assert not status.can_compute_matrix
    assert not status.can_solve


def test_migrated_solve_payload_attaches_the_matrix_and_issue_rows_flatten() -> None:
    workspace = current_workspace()
    payload = solve_payload(workspace)

    assert payload["routing_matrix"]["source"] == "test"
    assert "routing_matrix" not in workspace.scenario
    assert validation_issue_rows(
        {
            "issues": [
                {
                    "severity": "ERROR",
                    "code": "INVALID_VALUE",
                    "row_number": 2,
                    "field": "tasks.due_at",
                    "task_id": "TASK-1",
                    "message": "Due date is before ready time.",
                }
            ]
        }
    ) == [
        {
            "severity": "ERROR",
            "code": "INVALID_VALUE",
            "row_number": 2,
            "field": "tasks.due_at",
            "task_id": "TASK-1",
            "message": "Due date is before ready time.",
        }
    ]


# Readiness ---------------------------------------------------------------------------


def test_frontend_fingerprint_matches_the_backend_golden_values() -> None:
    """The same values are pinned in the backend tests (test_geocode_provenance.py)."""
    assert geocode_fingerprint(SUPPLIER_ADDRESS, "ca") == (
        "v1:ca:8392875975766cd34689822bd4d7b00da53eb83d4bca2af3e09a66d9ba916052"
    )
    assert geocode_fingerprint("100 Fixture Plant Road, Toronto, ON", None) == (
        "v1:-:c0693830671573be9e62edab32f173f6a4832db24818c2f21ee517991cb38a52"
    )
    assert geocode_fingerprint_matches(
        geocode_fingerprint(SUPPLIER_ADDRESS, "ca"), " 200 supplier AVENUE, vaughan, on "
    )
    assert not geocode_fingerprint_matches("garbage", SUPPLIER_ADDRESS)


def _location(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "location_id": "X",
        "name": "X",
        "address": SUPPLIER_ADDRESS,
        "latitude": 43.8,
        "longitude": -79.5,
        "geocode_status": "RESOLVED",
        "geocode_source_fingerprint": geocode_fingerprint(SUPPLIER_ADDRESS, "ca"),
        "geocoded_at": (NOW - timedelta(days=1)).isoformat(),
    }
    base.update(fields)
    return {key: value for key, value in base.items() if value is not None}


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({}, LocationReadiness.READY),
        (
            {"geocode_source_fingerprint": None, "geocoded_at": None, "geocode_status": None},
            LocationReadiness.SUPPLIED,
        ),
        (
            {"latitude": None, "longitude": None, "geocode_status": None},
            LocationReadiness.NOT_RESOLVED,
        ),
        ({"geocode_status": "NEEDS_REVIEW"}, LocationReadiness.NEEDS_REVIEW),
        (
            {"geocode_status": "NEEDS_REVIEW", "geocode_confirmed": True},
            LocationReadiness.READY,
        ),
        (
            {"geocode_status": "FAILED", "latitude": None, "longitude": None},
            LocationReadiness.FAILED,
        ),
        ({"address": "999 Other Road"}, LocationReadiness.STALE),
        ({"geocoded_at": (NOW - timedelta(days=30)).isoformat()}, LocationReadiness.EXPIRED),
        ({"geocoded_at": None}, LocationReadiness.EXPIRED),
        ({"geocoded_at": "not a date"}, LocationReadiness.EXPIRED),
    ],
    ids=[
        "resolved",
        "supplied",
        "not resolved",
        "needs review",
        "confirmed",
        "failed",
        "stale",
        "expired",
        "no timestamp",
        "bad timestamp",
    ],
)
def test_location_readiness(fields: dict[str, Any], expected: LocationReadiness) -> None:
    assert location_readiness(_location(**fields), now=NOW) is expected


def test_unsaved_edits_follow_the_saved_fingerprint() -> None:
    start = current_workspace()
    assert not workflow_status(start, now=NOW).unsaved_edits

    edited = _apply(lambda s: ss.set_fields(s, name="Changed"), start)
    assert workflow_status(edited, now=NOW).unsaved_edits

    reverted = _apply(lambda s: ss.set_fields(s, name="Freshness fixture"), edited)
    assert not workflow_status(reverted, now=NOW).unsaved_edits
