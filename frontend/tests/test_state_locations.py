"""V1.1-M3 address-resolution state: what is sent, what is applied, imports, copies."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any

import pytest

from frontend.state import locations as loc
from frontend.state.fingerprints import matrix_input_fingerprint, plan_input_fingerprint
from frontend.state.readiness import (
    LocationReadiness,
    geocode_fingerprint,
    readiness_by_location,
    workflow_status,
)
from frontend.state.scenario_state import ScenarioEditError, find_row, rename_location_id
from frontend.state.workspace import (
    current_estimate,
    edit,
    load_document,
    matrix_is_storable,
    record_estimate,
    record_matrix,
    record_resolutions,
    save_document,
    storable_matrix,
)
from frontend.tests.scenario_fixtures import NOW, SUPPLIER_ADDRESS, small_matrix, small_scenario

NEW_ADDRESS = "500 New Road, Toronto, ON"


def _resolved(location_id: str, address: str, **overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "location_id": location_id,
        "status": "RESOLVED",
        "reason_code": None,
        "reason_codes": [],
        "message": "Resolved.",
        "formatted_address": f"{address}, Canada",
        "alternatives": [],
        "place_id": f"place-{location_id}",
        "latitude": 43.71,
        "longitude": -79.41,
        "location_type": "ROOFTOP",
        "partial_match": False,
        "geocode_source_fingerprint": geocode_fingerprint(address, "ca"),
        "geocoded_at": NOW.isoformat(),
        "geocode_confirmed": False,
        "duplicate_of": [],
        "distance_from_plant_km": 10.0,
        "cache_hit": False,
    }
    result.update(overrides)
    return result


def _with_new_location() -> dict[str, Any]:
    return loc.add_location(small_scenario(), name="New Customer", address=NEW_ADDRESS)


def _readiness(scenario: dict[str, Any]) -> dict[str, LocationReadiness]:
    return readiness_by_location(scenario, now=NOW)


# --- what is sent ---------------------------------------------------------------------


def test_only_new_changed_or_expired_addresses_are_pending_plant_first() -> None:
    scenario = _with_new_location()
    scenario["locations"][1]["geocoded_at"] = (NOW - timedelta(days=31)).isoformat()
    scenario["locations"].append(
        {"location_id": "FAILED-ONE", "name": "Failed", "address": "x", "geocode_status": "FAILED"}
    )
    scenario["locations"].insert(0, scenario["locations"].pop(2))  # SPARE first in the list

    pending = loc.pending_ids(scenario, _readiness(scenario))

    assert pending == ["SUPPLIER_A", "NEW-CUSTOMER"]  # PLANT and SPARE are supplied
    assert loc.failed_ids(scenario, _readiness(scenario)) == ["FAILED-ONE"]


def test_the_plant_is_sent_first_when_pending() -> None:
    scenario = small_scenario()
    scenario["locations"] = [
        {"location_id": "SPARE", "name": "Spare", "address": "1 Spare St"},
        {"location_id": "PLANT", "name": "Plant", "address": "1 Plant St"},
    ]

    assert loc.pending_ids(scenario, _readiness(scenario)) == ["PLANT", "SPARE"]


def test_a_confirmed_place_is_sent_back_so_the_backend_does_not_ask_again() -> None:
    scenario = small_scenario()
    supplier = scenario["locations"][1]
    supplier["geocode_confirmed"] = True

    rows = loc.resolve_rows(scenario, ["SUPPLIER_A", "SPARE"])

    assert rows == [
        {
            "location_id": "SUPPLIER_A",
            "address": SUPPLIER_ADDRESS,
            "confirmed_place_id": "supplier-place",
        },
        {"location_id": "SPARE", "address": "300 Spare Street, Toronto, ON"},
    ]


def test_plant_coordinates_are_sent_only_when_the_plant_is_not_in_the_batch() -> None:
    scenario = _with_new_location()
    readiness = _readiness(scenario)

    assert loc.plant_coordinates(scenario, readiness, ["NEW-CUSTOMER"]) == {
        "latitude": 43.7,
        "longitude": -79.4,
    }
    assert loc.plant_coordinates(scenario, readiness, ["PLANT", "NEW-CUSTOMER"]) is None
    scenario["locations"][0] = {"location_id": "PLANT", "name": "Plant", "address": "1 Plant St"}
    assert loc.plant_coordinates(scenario, _readiness(scenario), ["NEW-CUSTOMER"]) is None


# --- what is applied ------------------------------------------------------------------


def test_a_resolved_result_fills_the_derived_fields_and_makes_the_location_ready() -> None:
    scenario = _with_new_location()

    applied = loc.apply_resolutions(
        scenario,
        [_resolved("NEW-CUSTOMER", NEW_ADDRESS)],
        sent_addresses={"NEW-CUSTOMER": NEW_ADDRESS},
    )

    location = find_row(applied.scenario, "locations", "NEW-CUSTOMER")
    assert location == {
        "location_id": "NEW-CUSTOMER",
        "name": "New Customer",
        "address": NEW_ADDRESS,
        "geocode_status": "RESOLVED",
        "formatted_address": f"{NEW_ADDRESS}, Canada",
        "place_id": "place-NEW-CUSTOMER",
        "latitude": 43.71,
        "longitude": -79.41,
        "geocode_source_fingerprint": geocode_fingerprint(NEW_ADDRESS, "ca"),
        "geocoded_at": NOW.isoformat(),
        "geocode_location_type": "ROOFTOP",
        "geocode_partial_match": False,
        "geocode_confirmed": False,
    }
    assert applied.applied == ("NEW-CUSTOMER",)
    assert _readiness(applied.scenario)["NEW-CUSTOMER"] is LocationReadiness.READY


def test_review_and_failed_results_are_kept_with_their_reason() -> None:
    scenario = loc.add_location(_with_new_location(), name="Lost", address="Nowhere 1")
    review = _resolved(
        "NEW-CUSTOMER",
        NEW_ADDRESS,
        status="NEEDS_REVIEW",
        reason_code="LOW_PRECISION",
        reason_codes=["LOW_PRECISION"],
        message="Google found only an approximate area.",
        location_type="APPROXIMATE",
    )
    failed = {
        "location_id": "LOST",
        "status": "FAILED",
        "reason_codes": ["ADDRESS_NOT_FOUND"],
        "message": "Google did not find this address.",
        "latitude": None,
        "longitude": None,
    }

    applied = loc.apply_resolutions(
        scenario,
        [review, failed],
        sent_addresses={"NEW-CUSTOMER": NEW_ADDRESS, "LOST": "Nowhere 1"},
    )

    readiness = _readiness(applied.scenario)
    assert readiness["NEW-CUSTOMER"] is LocationReadiness.NEEDS_REVIEW
    assert readiness["LOST"] is LocationReadiness.FAILED
    lost = find_row(applied.scenario, "locations", "LOST")
    assert lost == {
        "location_id": "LOST",
        "name": "Lost",
        "address": "Nowhere 1",
        "geocode_status": "FAILED",
        "geocode_warning": "Google did not find this address.",
    }
    review_row = find_row(applied.scenario, "locations", "NEW-CUSTOMER")
    assert review_row is not None
    assert review_row["geocode_warning"] == "Google found only an approximate area."


def test_a_result_for_an_address_that_changed_meanwhile_is_not_applied() -> None:
    scenario = _with_new_location()
    edited = loc.edit_location(scenario, "NEW-CUSTOMER", name="New Customer", address="9 Other St")

    applied = loc.apply_resolutions(
        edited,
        [_resolved("NEW-CUSTOMER", NEW_ADDRESS)],
        sent_addresses={"NEW-CUSTOMER": NEW_ADDRESS},
    )

    assert applied.skipped == ("NEW-CUSTOMER",)
    assert applied.scenario == edited


def test_confirming_a_review_match_makes_it_ready_and_confirmed() -> None:
    scenario = _with_new_location()
    review = _resolved("NEW-CUSTOMER", NEW_ADDRESS, status="NEEDS_REVIEW")
    applied = loc.apply_resolutions(
        scenario, [review], sent_addresses={"NEW-CUSTOMER": NEW_ADDRESS}
    ).scenario

    confirmed = loc.confirm_match(applied, "NEW-CUSTOMER")

    location = find_row(confirmed, "locations", "NEW-CUSTOMER")
    assert location is not None
    assert location["geocode_status"] == "RESOLVED"
    assert location["geocode_confirmed"] is True
    assert _readiness(confirmed)["NEW-CUSTOMER"] is LocationReadiness.READY
    with pytest.raises(ScenarioEditError):
        loc.confirm_match(confirmed, "NEW-CUSTOMER")
    with pytest.raises(ScenarioEditError):
        loc.confirm_match(confirmed, "NOPE")


# --- edits and their effect downstream ----------------------------------------------


def test_an_address_edit_resets_only_that_location_and_stales_travel_times() -> None:
    workspace = record_matrix(
        load_document(small_scenario(), source="t"), small_matrix(), origin="x"
    )
    before = deepcopy(workspace.scenario)

    edited = edit(
        workspace,
        loc.edit_location(before, "SUPPLIER_A", name="Supplier A", address="1 Moved Rd"),
    )

    readiness = readiness_by_location(edited.scenario, now=NOW)
    assert readiness["SUPPLIER_A"] is LocationReadiness.NOT_RESOLVED
    assert edited.scenario["locations"][0] == before["locations"][0]
    assert edited.scenario["locations"][2] == before["locations"][2]
    assert not workflow_status(edited, now=NOW).matrix_current


def test_a_name_edit_keeps_travel_times_and_plan_inputs() -> None:
    scenario = small_scenario()

    renamed = loc.edit_location(scenario, "SUPPLIER_A", name="Acme", address=SUPPLIER_ADDRESS)

    assert matrix_input_fingerprint(renamed) == matrix_input_fingerprint(scenario)
    assert plan_input_fingerprint(renamed, small_matrix()) == plan_input_fingerprint(
        scenario, small_matrix()
    )
    assert find_row(renamed, "locations", "SUPPLIER_A")["latitude"] == 43.82  # type: ignore[index]


def test_a_spacing_or_case_change_is_not_an_address_change() -> None:
    scenario = small_scenario()

    edited = loc.edit_location(
        scenario, "SUPPLIER_A", name="Supplier A", address="  200 SUPPLIER avenue,  Vaughan, ON "
    )

    assert _readiness(edited)["SUPPLIER_A"] is LocationReadiness.READY


def test_adding_needs_a_name_and_an_address_and_suggests_a_unique_id() -> None:
    scenario = loc.add_location(small_scenario(), name="Spare Dock", address="1 A St")
    scenario = loc.add_location(scenario, name="Spare  Dock", address="2 B St")

    ids = [row["location_id"] for row in scenario["locations"]]
    assert ids[-2:] == ["SPARE-DOCK", "SPARE-DOCK-2"]
    assert find_row(scenario, "locations", "SPARE-DOCK-2") == {
        "location_id": "SPARE-DOCK-2",
        "name": "Spare Dock",
        "address": "2 B St",
    }
    for name, address in (("", "1 A St"), ("Name", "  ")):
        with pytest.raises(ScenarioEditError):
            loc.add_location(scenario, name=name, address=address)
    with pytest.raises(ScenarioEditError):
        loc.add_location(scenario, name="X", address="Y", location_id="PLANT")
    with pytest.raises(ScenarioEditError):
        loc.add_location(scenario, name="X", address="Y", location_id="bad id")


def test_duplicating_keeps_the_resolution_under_a_new_id() -> None:
    scenario, new_id = loc.duplicate_location(small_scenario(), "SUPPLIER_A")

    assert new_id == "SUPPLIER_A-2"
    copy = find_row(scenario, "locations", new_id)
    assert copy is not None
    assert copy["name"] == "Supplier A (copy)"
    assert _readiness(scenario)[new_id] is LocationReadiness.READY


def test_unused_locations_and_used_by_text() -> None:
    scenario = small_scenario()

    assert loc.unused_ids(scenario) == ["SPARE"]
    assert loc.used_by(scenario, "PLANT") == "Plant; used by 1 task and 1 shift"
    assert loc.used_by(scenario, "SUPPLIER_A") == "Used by 1 task"
    assert loc.used_by(scenario, "SPARE") == "Not used"


def test_table_rows_pin_the_plant_first_and_never_show_coordinates() -> None:
    scenario = small_scenario()
    scenario["locations"].reverse()

    table = loc.table_rows(scenario, _readiness(scenario))

    assert [row["ID"] for row in table] == ["PLANT", "SPARE", "SUPPLIER_A"]
    assert table[0]["Name"] == "🏭 Plant"
    assert table[2]["Matched address"] == "200 Supplier Ave, Vaughan, ON, Canada"
    assert table[2]["Status"] == "Resolved"
    assert table[1]["Status"] == "Supplied coordinates"
    assert all(
        "latitude" not in key.casefold() and "longitude" not in key.casefold()
        for row in table
        for key in row
    )


# --- import and copy ------------------------------------------------------------------


def test_import_adds_updates_by_id_or_unique_name_and_reports_unchanged() -> None:
    scenario = small_scenario()

    outcome = loc.merge_imported_locations(
        scenario,
        [
            {"name": "Supplier A", "address": SUPPLIER_ADDRESS},  # unchanged, matched by name
            {"name": "Spare dock", "address": "301 Spare Street, Toronto, ON"},  # moved
            {
                "location_id": "PLANT",
                "name": "Head office plant",
                "address": "100 Plant Road, Toronto, ON",
            },
            {"name": "New Customer", "address": NEW_ADDRESS},
            {"location_id": "CUST-9", "name": "Customer Nine", "address": "9 Nine St"},
        ],
    )

    assert outcome.added == ("NEW-CUSTOMER", "CUST-9")
    assert outcome.updated == ("SPARE", "PLANT")
    assert outcome.unchanged == ("SUPPLIER_A",)
    readiness = _readiness(outcome.scenario)
    assert readiness["SPARE"] is LocationReadiness.NOT_RESOLVED
    assert readiness["PLANT"] is LocationReadiness.SUPPLIED  # a name change keeps coordinates
    assert readiness["NEW-CUSTOMER"] is LocationReadiness.NOT_RESOLVED
    assert scenario == small_scenario()  # the input is never changed


def test_an_invalid_import_row_raises_and_applies_nothing() -> None:
    scenario = small_scenario()
    with pytest.raises(ScenarioEditError):
        loc.merge_imported_locations(
            scenario, [{"name": "Good", "address": "1 Good St"}, {"name": "Bad", "address": ""}]
        )
    assert scenario == small_scenario()


def test_copying_keeps_provenance_skips_known_addresses_and_renames_taken_ids() -> None:
    source = small_scenario()["locations"]
    target = loc.add_location(
        {**small_scenario(), "locations": []}, name="Supplier A", address="Somewhere else 1"
    )
    target["locations"][0]["location_id"] = "SUPPLIER_A"
    target = loc.add_location(target, name="Spare", address="300 Spare Street, Toronto, ON")

    outcome = loc.copy_locations(target, source)

    assert outcome.added == ("PLANT", "SUPPLIER_A-2")
    assert outcome.skipped == ("SPARE",)
    copied = find_row(outcome.scenario, "locations", "SUPPLIER_A-2")
    assert copied is not None
    assert copied["geocode_source_fingerprint"] == geocode_fingerprint(SUPPLIER_ADDRESS, "ca")
    assert _readiness(outcome.scenario)["SUPPLIER_A-2"] is LocationReadiness.READY


def test_copied_coordinates_older_than_30_days_are_not_used() -> None:
    source = deepcopy(small_scenario()["locations"][1])
    source["geocoded_at"] = (NOW - timedelta(days=45)).isoformat()

    outcome = loc.copy_locations({**small_scenario(), "locations": []}, [source])

    assert _readiness(outcome.scenario)["SUPPLIER_A"] is LocationReadiness.EXPIRED
    assert loc.pending_ids(outcome.scenario, _readiness(outcome.scenario)) == ["SUPPLIER_A"]


# --- workspace: session details, estimates, and decision D6 -----------------------------


def test_resolve_details_are_kept_for_the_session_and_follow_renames() -> None:
    workspace = load_document(_with_new_location(), source="t")
    result = _resolved(
        "NEW-CUSTOMER", NEW_ADDRESS, status="NEEDS_REVIEW", alternatives=["500 New Rd W"]
    )
    applied = loc.apply_resolutions(
        workspace.scenario, [result], sent_addresses={"NEW-CUSTOMER": NEW_ADDRESS}
    )

    updated = record_resolutions(
        workspace, applied.scenario, [result], sent_addresses={"NEW-CUSTOMER": NEW_ADDRESS}
    )

    details = updated.derived.resolutions["NEW-CUSTOMER"]
    assert details["alternatives"] == ["500 New Rd W"]
    assert details["address"] == NEW_ADDRESS
    renamed = edit(
        updated,
        rename_location_id(updated.scenario, "NEW-CUSTOMER", "CUST-1"),
        renamed_locations={"NEW-CUSTOMER": "CUST-1"},
    )
    assert "CUST-1" in renamed.derived.resolutions


def test_an_estimate_is_remembered_only_for_the_inputs_it_was_made_for() -> None:
    workspace = load_document(small_scenario(), source="t")
    estimated = record_estimate(workspace, {"billable_element_count": 9})

    assert current_estimate(estimated) == {"billable_element_count": 9}
    renamed = edit(
        estimated,
        loc.edit_location(
            estimated.scenario, "SPARE", name="Dock", address="300 Spare Street, Toronto, ON"
        ),
    )
    assert current_estimate(renamed) is not None
    moved = edit(
        estimated, loc.edit_location(estimated.scenario, "SPARE", name="Dock", address="1 Moved St")
    )
    assert current_estimate(moved) is None


def test_google_travel_times_are_left_out_of_saves_decision_d6() -> None:
    workspace = load_document(small_scenario(), source="t")
    google = {**small_matrix(), "source": "google_routes"}
    fixture = {**small_matrix(), "source": "deterministic_offline_fixture"}

    with_google = record_matrix(workspace, google, origin="calculated")
    with_fixture = record_matrix(workspace, fixture, origin="json")

    assert not matrix_is_storable(google)
    assert matrix_is_storable(fixture)
    assert storable_matrix(with_google) is None
    assert "routing_matrix" not in save_document(with_google)
    assert save_document(with_google)["locations"][1]["latitude"] == 43.82
    assert (
        save_document(with_fixture)["routing_matrix"]["source"] == "deterministic_offline_fixture"
    )
    assert workflow_status(with_google, now=NOW).matrix_current  # still usable in the session
